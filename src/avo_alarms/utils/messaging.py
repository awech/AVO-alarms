import json
import os
import re
import smtplib
import time
import warnings
from pandas import Timestamp
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
import urllib3
import yaml

from avo_alarms.utils.setup_utils import get_logger

logger = get_logger(__name__)

warnings.filterwarnings("ignore")

def icinga(config, state, state_message, send=True):
    """Send alarm state and message to Icinga monitoring system.

    Parameters
    ----------
    config : object
        Configuration object containing alarm settings and optional icinga_service_name
    state : str
        The state to report (OK, WARNING, CRITICAL, or UNKNOWN)
    state_message : str
        The message describing the current state
    send : bool, optional
        Whether to actually send the message to Icinga2, by default True

    Returns
    -------
    None
    """

    if not send:
        logger.info("Not attempting to send heartbeat to icinga.")
        return

    logger.info("Sending state and message to icinga:")
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    states = {"OK": 0, "WARNING": 1, "CRITICAL": 2, "UNKNOWN": 3}

    state_num = states[state]

    #### which icinga service ####
    ##############################
    if hasattr(config, "icinga_service_name"):
        icinga_service_name = config.icinga_service_name
    else:
        icinga_service_name = config.alarm_name
    ##############################
    ##############################

    headers = {"Accept": "application/json", "X-HTTP-Method-Override": "POST"}
    data = {
        "type": "Service",
        "filter": 'host.name=="{}" && service.name=="{}"'.format(
            os.environ["ICINGA_HOST_NAME"], icinga_service_name
        ),
        "exit_status": state_num,
        "plugin_output": state_message,
    }

    try:
        resp = requests.get(
            os.environ["ICINGA_URL"],
            headers=headers,
            auth=(os.environ["ICINGA_USERNAME"], os.environ["ICINGA_PASSWORD"]),
            data=json.dumps(data),
            verify=False,
            timeout=10,
        )
        if resp.status_code == 200:
            logger.info(resp.json()["results"][0]["status"])
            logger.info("Success. Message sent to icinga2")
        else:
            logger.info("Status code = {:g}".format(resp.status_code))
            logger.error("Failed to send message to icinga2")
    except Exception as e:
        logger.error("requests error. Failed to send message to icinga")
        logger.error(f"An unexpected error occurred: {e}")

    return


def attachments_tolist(attachment):
    """Convert attachment(s) to a list format.

    Parameters
    ----------
    attachment : str, list, or None
        A single file path, list of file paths, or None

    Returns
    -------
    list
        A list of attachment file paths. Returns empty list if None provided.
    """
    if not attachment:
        attachment = []
    else:
        if not isinstance(attachment, list):
            attachment = [attachment]
    return attachment


def get_recipients_list(alarm_name, test=False):
    """Retrieve recipient email addresses for a given alarm from distribution list.

    Parameters
    ----------
    alarm_name : str
        Name of the alarm to look up recipients for
    test : bool, optional
        If True, returns error recipients for testing purposes, by default False

    Returns
    -------
    list
        List of recipient email addresses from distribution.yml and phonebook.yml
    """

    # read & parse notification list
    config_dir = Path(os.environ["CONFIGS_DIR"])
    with open(config_dir / "distribution.yml", "r") as file:
        distribution = yaml.safe_load(file)

    # read & parse phonebook
    home_dir = Path(os.environ["HOME_DIR"])
    with open(home_dir / "phonebook.yml", "r") as file:
        users = yaml.safe_load(file) 

    alarm_key = alarm_name
    if test:
        alarm_key = "Error"
        logger.info("Test mode. Sending message to 'Error' recipients")
    else:
        if alarm_name not in distribution.keys():
            alarm_key = "All Alarms"
            logger.info("Defaulting to 'All alarms' list")
        else:
            logger.info(f"Sending to '{alarm_name}' recipients")

    recipients = []
    for user in distribution[alarm_key]:
        if user not in users:
            logger.error(f"\nERROR!! {user} not in phonebook! No message sent to {user}")
            continue
        recipients.append(users[user])
        logger.info(f"{user}: {users[user]}")      

    if not recipients:
        logger.warning(f"No recipient found. Check distribution list for {alarm_name}")

    return recipients


def send_alert(alarm_name, subject, body, attachment=None, test=False):
    """Send alarm alert via email with optional attachments.

    Parameters
    ----------
    alarm_name : str
        Name of the alarm to include in the from address
    subject : str
        Email subject line
    body : str
        Email body content
    attachment : str, list, or None, optional
        File path(s) to attach to the email, by default None
    test : bool, optional
        If True, sends to error recipients list, by default False

    Returns
    -------
    None
    """

    logger.info("Sending alarm email and sms...")

    recipients = get_recipients_list(alarm_name, test=test)
    fromaddr = alarm_name.replace(" ", "_") + "@usgs.gov"

    if test:
        subject = f"TEST: {subject}"

    msg = MIMEMultipart()
    msg["From"] = fromaddr
    msg["Subject"] = subject
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(body, "plain"))

    attachment_list = attachments_tolist(attachment)
    for file in attachment_list:
        with open(file, "rb") as attachment:
            part = MIMEBase("image", "jpeg")
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f"attachment; filename={file.name}")
            msg.attach(part)

    server = smtplib.SMTP_SSL(
        host=os.environ["SMTP_IP"], port=os.environ["SMTP_PORT"]
    )
    text = msg.as_string()
    server.sendmail(fromaddr, recipients, text)
    server.quit()

    return


def connect_mattermost():
    """Establish and authenticate connection to Mattermost server.

    Uses environment variables:
    - MATTERMOST_SERVER_URL
    - MATTERMOST_USER_ID
    - MATTERMOST_USER_PASS
    - SSL_CA

    Returns
    -------
    mattermostdriver.Driver
        Authenticated Mattermost driver instance
    """
    from mattermostdriver import Driver
    
    mm = Driver(
        {
            "url": os.environ["MATTERMOST_SERVER_URL"],
            "login_id": os.environ["MATTERMOST_USER_ID"],
            "password": os.environ["MATTERMOST_USER_PASS"],
            "scheme": "https",
            "port": 443,
            "verify": os.environ["SSL_CA"],
        }
    )
    mm.login();  # noqa: E703

    return mm


def format_mm_message(subject, body, config):
    """Format alarm message for Mattermost post with markdown formatting.

    Parameters
    ----------
    subject : str
        Message subject/title
    body : str
        Message body content with alarm data
    config : object
        Configuration object containing alarm_name

    Returns
    -------
    str
        Formatted message with Mattermost markdown syntax
    """
    p = re.compile(r"\\n(.*)\*(:.*)", re.MULTILINE)
    body = p.sub(r"\n- [x] __***\1\2***__", body)
    p = re.compile("\\n([A-Z,1-9]{3,4}:.*/.*)", re.MULTILINE)
    body = p.sub(r"\n- [ ] \1", body)

    body = body.replace("Start: ", "Start:  ")
    body = body.replace("End: ", "End:    ")

    if config.alarm_name != "PIREP":
        subject = subject.replace("--- ", "")
        subject = subject.replace(" ---", "")
        message = "### **{}**\n\n{}".format(subject, body)
    else:
        if "URGENT" in subject:
            message = "### **{}**\n\n{}".format(subject, body)
        else:
            message = "#### **{}**\n\n{}".format(subject, body)

    return message


def upload_mm_attachments(mm, channel_id, attachment):
    """Upload attachment files to a Mattermost channel.

    Parameters
    ----------
    mm : mattermostdriver.Driver
        Authenticated Mattermost driver instance
    channel_id : str
        ID of the target Mattermost channel
    attachment : str, list, or None
        File path(s) to upload

    Returns
    -------
    list
        List of uploaded file IDs from Mattermost
    """
    upload_files = attachments_tolist(attachment)

    ## Upload attachment(s)
    file_ids = []
    for file in upload_files:
        with open(file, 'rb') as f:
            file_info = mm.files.upload_file(
                channel_id=channel_id,
                files={'files': (file.name, f)}
            )['file_infos'][0]
            file_ids.append(file_info['id'])

    return file_ids


def post_mattermost(config, subject, body, attachment=None, send=False, test=False, volcano=None):
    """Post alarm message to Mattermost channel with optional attachments.

    Parameters
    ----------
    config : object
        Configuration object containing alarm_name and optional mattermost_channel_id
    subject : str
        Message subject/title
    body : str
        Message body content
    attachment : str, list, or None, optional
        File path(s) to attach to the post, by default None
    send : bool, optional
        Whether to actually post to Mattermost, by default False
    test : bool, optional
        If True, posts to test channel and prefixes subject with "TEST:", by default False

    Returns
    -------
    str
        URL of the posted message, or empty string if send=False
    """

    if not send:
        logger.info("Not posting anything to Mattermost")
        return ""

    logger.info("Posting to mattermost...")

    channel_id = os.environ["MATTERMOST_DEFAULT_CHANNEL_ID"]
    if hasattr(config, "mattermost_channel_id"):
        channel_id = config.mattermost_channel_id      

    if test:
        channel_id = os.environ["MATTERMOST_TEST_CHANNEL_ID"]
        subject = f"TEST: {subject}"

    mm = connect_mattermost()
    file_ids = upload_mm_attachments(mm, channel_id, attachment)
    message = format_mm_message(subject, body, config)

    message_details = {
        "channel_id": channel_id,
        "message": message,
        "file_ids": file_ids
    }

    try:
        post = mm.posts.create_post(options=message_details)
    except Exception as e:
        logger.error("Error posting to Mattermost. Retrying once...")
        logger.error(f"An unexpected error occurred: {e}")
        time.sleep(2)
        post = mm.posts.create_post(options=message_details)

    url = f"mattermost://{os.environ['MATTERMOST_POST_URL']}/{post['id']}"

    if not test and volcano is not None:
        if volcano in getattr(config, "mm_response_channels", "empty"):
            logger.info(f"Posting to {volcano} Mattermost response channel")
            volcano_channel_id = config.mm_response_channels[volcano]
            volcano_file_ids = upload_mm_attachments(mm, volcano_channel_id, attachment)
            message_details = {
                "channel_id": volcano_channel_id,
                "message": message,
                "file_ids": volcano_file_ids,
            }
            post = mm.posts.create_post(options=message_details)
    
    return url


def cimss_mm_channels(alert, config, subject, message, attachment, test_flag, mm_flag):
    
    ##################################################################
    # Send thermal alerts to their own channel
    if (alert.alert_type == "hot") and ("THERMAL" in alert.alert_header):
        if alert.v_distance < getattr(config, "thermal_alert_dist", 20):
            config.mattermost_channel_id = config.thermal_alerts_mm
            post_mattermost(config, subject, message, attachment=attachment, send=mm_flag, test=test_flag)
    ##################################################################

    ##################################################################
    # Send alerts for elevated volcanoes to their own channel
    if (alert.v_distance < config.elevated_volcano_dist) and (alert.v_name in config.elevated_volcano_list):
        config.mattermost_channel_id = config.elevated_volcano_mm
        post_mattermost(config, subject, message, attachment=attachment, send=mm_flag, test=test_flag)
    ##################################################################

    return


def format_timestring(t1, t2=None):

    t1_str = t1.strftime("%Y-%m-%d %H:%M")
    t1_local = Timestamp(t1.datetime, tz="UTC")
    t1_local = t1_local.tz_convert(os.environ["TIMEZONE"])
    t1_local_str = t1_local.strftime("%Y-%m-%d %H:%M")

    if t2 is not None:    
        t2_str = t2.strftime("%Y-%m-%d %H:%M")
        t2_local = Timestamp(t2.datetime, tz="UTC")
        t2_local = t2_local.tz_convert(os.environ["TIMEZONE"])
        t2_local_str = t2_local.strftime("%Y-%m-%d %H:%M")

        time_str = f"Start: {t1_str} (UTC)\nEnd: {t2_str} (UTC)\n\n"
        time_str = f"{time_str}Start: {t1_local_str} ({t1_local.tzname()})"
        time_str = f"{time_str}\nEnd: {t2_local_str} ({t2_local.tzname()})"
    else:
        time_str = f"{t1_str} UTC\n{t1_local_str} {t1_local.tzname()}"

    return time_str