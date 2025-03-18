import json
import os
import re
import smtplib
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests
import urllib3
from pandas import read_excel
from tomputils import mattermost as mm
import warnings
warnings.filterwarnings("ignore")

def icinga(config, state, state_message, test=False):
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

    if test:

        return

    else:

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        print("Sending state and message to icinga2:")

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


def send_alert(alarm_name, subject, body, filename=None, test=False):
    """_summary_

    Parameters
    ----------
    alarm_name : _type_
        _description_
    subject : _type_
        _description_
    body : _type_
        _description_
    filename : _type_, optional
        _description_, by default None
    test : _type_, optional
        _description_, by default test
    """

    if test:
        print("Test mode. No sms or email sent")
        return

    else:

        print("Sending alarm email and sms...")

        # read & parse notification list
        home_dir = Path(os.environ["HOME_DIR"])
        A = read_excel(home_dir / "distribution.xlsx")

        if alarm_name in A.columns:
            recipients = A[A[alarm_name].notna()]["Email"].tolist()
        else:
            recipients = A[A["All"].notna()]["Email"].tolist()
        if not recipients:
            print(f"No recipient found for . Check distribution list for {alarm_name}")
            return

        msg = MIMEMultipart()

        fromaddr = alarm_name.replace(" ", "_") + "@usgs.gov"
        msg["From"] = fromaddr
        msg["Subject"] = subject
        msg["To"] = ", ".join(recipients)

        msg.attach(MIMEText(body, "plain"))

        if filename:
            name = filename.name
            attachment = open(filename, "rb")
            part = MIMEBase("application", "octet-stream")
            part.set_payload((attachment).read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition", "attachment; filename= {}".format(name)
            )
            msg.attach(part)

        server = smtplib.SMTP_SSL(
            host=os.environ["SMTP_IP"], port=os.environ["SMTP_PORT"]
        )
        text = msg.as_string()
        server.sendmail(fromaddr, recipients, text)
        server.quit()

        return


def post_mattermost(config, subject, body, filename=None, test=False):
    """_summary_

    Parameters
    ----------
    config : _type_
        _description_
    subject : _type_
        _description_
    body : _type_
        _description_
    filename : _type_, optional
        _description_, by default None
    test : bool, optional
        _description_, by default False
    """

    if test:
        return
    else:

        conn = mm.Mattermost(timeout=5, retries=4)

        if hasattr(config, "mattermost_channel_id"):
            conn.channel_id = config.mattermost_channel_id
        else:
            conn.channel_id = os.environ["MATTERMOST_DEFAULT_CHANNEL_ID"]

        if not filename:
            files = []
        else:
            files = [filename]

        p = re.compile("\\n(.*)\*(:.*)", re.MULTILINE)
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

        try:
            conn.post(message, file_paths=files)
        except:
            conn.post(message, file_paths=files)

        return
