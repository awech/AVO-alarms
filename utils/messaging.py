import json
import os
import re
import smtplib
import time
import warnings
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
import urllib3
import yaml
from mattermostdriver import Driver

warnings.filterwarnings("ignore")

def icinga(config, state, state_message, send=True):
    """_summary_

    Parameters
    ----------
    config : _type_
        _description_
    state : _type_
        _description_
    state_message : _type_
        _description_
    test : bool, optional
        _description_, by default False
    """

    if not send:
        print("Not attempting to send heartbeat to icinga.")
        return

    print("Sending state and message to icinga2:")
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
            print(resp.json()["results"][0]["status"])
            print("Success. Message sent to icinga2")
        else:
            print("Status code = {:g}".format(resp.status_code))
            print("Failed to send message to icinga2")
    except:

        print("requests error. Failed to send message to icinga2")

    return


def attachments_tolist(attachment):
    if not attachment:
        attachment = []
    else:
        if not isinstance(attachment, list):
            attachment = [attachment]
    return attachment


def get_recipients_list(alarm_name, test=False):
    """
    Parameters
    ----------
    alarm_name : _type_
        _description_
    test : _type_, optional
        _description_, by default test
    """

    config_dif = Path(os.environ.get("CONFIGS_DIR"))
    home_dir = Path(os.environ["HOME_DIR"])
    # read & parse notification list
    with open(config_dif / "distribution.yml", "r") as file:
        distribution = yaml.safe_load(file)
    # read & parse phonebook
    with open(home_dir / "phonebook.yml", "r") as file:
        users = yaml.safe_load(file) 

    alarm_key = alarm_name
    if alarm_name not in distribution.keys():
        alarm_key = "All Alarms"
        print("Defaulting to \'All alarms\' list")
        
    else:
        print(f"Sending to '{alarm_name}' recipients")

    if test:
        alarm_key = "Error"
        print("Test mode. Sending message to \'Error\' recipients")

    recipients = []
    for user in distribution[alarm_key]:
        if user not in users:
            print(f"\nERROR!! {user} not in phonebook! No message sent to {user}")
            continue
        recipients.append(users[user])
        print(f"{user}: {users[user]}")      

    if not recipients:
        print(f"No recipient found. Check distribution list for {alarm_name}")

    return recipients


def send_alert(alarm_name, subject, body, attachment=None, test=False):
    """
    Parameters
    ----------
    alarm_name : _type_
        _description_
    subject : _type_
        _description_
    body : _type_
        _description_
    attachment : _type_, optional
        _description_, by default None
    test : _type_, optional
        _description_, by default test
    """

    print("Sending alarm email and sms...")

    recipients = get_recipients_list(alarm_name, test=test)
    fromaddr = alarm_name.replace(" ", "_") + "@usgs.gov"

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
            part.add_header("Content-Disposition", f"attachment; filename={file}")
            msg.attach(part)

    server = smtplib.SMTP_SSL(
        host=os.environ["SMTP_IP"], port=os.environ["SMTP_PORT"]
    )
    text = msg.as_string()
    server.sendmail(fromaddr, recipients, text)
    server.quit()

    return


def connect_mattermost():
    ## Connect to Mattermost
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
    mm.login();

    return mm


def format_mm_message(subject, body, config):
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


def post_mattermost(config, subject, body, attachment=None, send=False, test=False):
    """_summary_

    Parameters
    ----------
    config : _type_
        _description_
    subject : _type_
        _description_
    body : _type_
        _description_
    attachment : _type_, optional
        _description_, by default None
    test : bool, optional
        _description_, by default False
    """

    if not send:
        print("Not posting anything to Mattermost")
        return ""

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
    except:
        time.sleep(2)
        post = mm.posts.create_post(options=message_details)

    url = f"mattermost://{os.environ["MATTERMOST_POST_URL"]}/{post['id']}"
    
    return url
