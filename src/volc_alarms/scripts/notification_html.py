import argparse
import os
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from volc_alarms.utils.setup_utils import (
    get_logger,
    load_environment,
    setup_root_logger,
    LockFile,
)


def parse_args():
    parser = argparse.ArgumentParser(prog="update-html")
    parser.add_argument(
        "--env-file",
        type=str,
        help="Path to a .env file (optional, otherwise searches up the directory tree)",
        required=False,
    )
    return parser.parse_args()


def main():
    args = parse_args()
    load_environment(args.env_file)

    # Log and set lock directory based on cron status
    if os.getenv("FROMCRON") == "yep":
        setup_root_logger(log_dir=os.environ.get("LOGS_DIR"), config_name="Notification_HTML")
        lock_dir = os.getenv("LOCK_DIR", os.getenv("LOGS_DIR"))
    else:
        setup_root_logger()
        lock_dir = Path.home() / ".tmp" / "alarms"

    logger = get_logger(__name__)
    logger.info("Generating notification HTML")
    try:
        lock = LockFile(lock_dir, "Notification_HTML")
        lock.acquire()
    except RuntimeError as e:
        logger.warning(str(e))
        return

    try:
        dist_file = Path(os.environ["DISTRIBUTION_FILE"])
        with open(dist_file, "r") as file:
            distribution = yaml.safe_load(file)
        alarms = [alarm for alarm in distribution]
        users = []
        for alarm in alarms:
            users += distribution[alarm]
        A = pd.DataFrame(index=alarms, columns=np.unique(users))
        for alarm in alarms:
            A.loc[alarm, distribution[alarm]] = "x"

        def highlight_vals(val):
            string = "font-family: Helvetica; "
            if val == "x":
                string += "background-color: #8CDD81; text-align: center; color: #3B5323; font-weight: bold; border-radius: 5px;"
            return string

        A = A.replace(np.nan, " ", regex=True)
        B = A.copy().T
        B = B.style.set_table_styles([
                {'selector': 'th', 'props': 
                    [
                        ('font-weight', 'bold'),
                        ('font-family', 'Helvetica'),
                    ]},
                {'selector': 'thead tr th:not(:first-child)', 'props':
                    [
                        ('background-color', 'whitesmoke'),
                        ('vertical-align', 'middle'),
                        ('padding-bottom', '5px'),
                        ('padding-left', '10px'),
                        ('padding-right', '10px')           
                    ]},
                {'selector': 'td:first-child, th:first-child', 'props':
                    [
                        ('text-align', 'right'),
                        ('padding-left', '10px'),
                        ('padding-right', '10px'),
                        ('background-color', 'whitesmoke')
                    ]},

            ])
        B = B.map(highlight_vals)

        html_output = B.to_html()
        # Add a <style> block to the HTML string to center the table using CSS
        centered_html = f"""
        <html>
        <head>
        <style>
            table {{
                margin-left: auto;
                margin-right: auto;
                /* Optional: also center text within cells */
                text-align: center;
            }}
            th {{
                text-align: center;
            }}
        </style>
        </head>
        <body>
        {html_output}
        </body>
        </html>
        """

        # You can save this to an HTML file and open it in a browser
        out_file = Path(os.environ["WWW_FILE"])
        with open(out_file, "w") as f:
            f.write(centered_html)
        logger.info("Notification HTML generated successfully")
    finally:
        lock.release()


if __name__ == "__main__":
    main()
