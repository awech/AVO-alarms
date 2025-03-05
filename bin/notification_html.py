import os
import sys
import pandas as pd
import numpy as np
from pathlib import Path
from dotenv import load_dotenv

current_path = Path(__file__).parent
sys.path.append(str(current_path.parents[0]))
load_dotenv()


def update_html():

    A = pd.read_excel(os.environ["HOME_DIR"] + "/distribution.xlsx")
    del A["Error"]
    A.rename(columns={"Name": "who", "Email": "address"}, inplace=True)

    who = A["who"]
    add = A["address"]
    A = A.replace(r"\bx\b", 1.0, regex=True)
    A = A.replace(r"\bo\b", 0.0, regex=True)
    A = A.replace(np.nan, 0.0, regex=True)

    af = A.copy()
    del af["who"]
    del af["address"]

    sums = af.sum(axis="columns", numeric_only=True)
    sums = sums[np.invert(sums > 0)]
    A = A.drop(sums.index)
    who = who.drop(sums.index)
    add = add.drop(sums.index)
    A["who"] = who
    A["address"] = add
    del A["address"]

    A["who"] = A.who.str.capitalize()
    A = A.sort_values(by="who")
    A = A.reset_index(drop=True)

    def highlight_vals(val):
        string = "font-family: Helvetica; "
        if val == "x":
            string += "background-color: #8CDD81; text-align: center; color: #3B5323; font-weight: bold;"
        elif val == "o":
            string += "background-color: #FBEC5D; text-align: center; color: #8B7500; font-weight: bold;"
        elif "cell" in val:
            string += "text-align: left; font-weight: bold; color: red;"
        elif "email" in val:
            string += "text-align: left;"
        return string

    A = A.replace(np.nan, " ", regex=True)
    A = A.replace(0.0, "", regex=True)
    A = A.replace(1.0, "x", regex=True)
    A = A.replace("_", " ", regex=True)
    A = A.replace("phone", "cell", regex=True)

    B = A.copy().T

    names = B.loc["who"]
    B.columns = names
    B = B.drop("who")

    try:
        df1 = B.pop("Wech email")  # remove column b and store it in df1
        B["Wech email"] = df1  # add b series as a 'new' column.
    except:
        pass
    try:
        df2 = B.pop("Lopez cell")  # remove column x and store it in df2
        B["Lopez cell"] = df2  # add b series as a 'new' column.
    except:
        pass

    B.columns.name = ""

    B = B.style.set_properties(**{"font-family": "Hevletica"})
    B = B.applymap(highlight_vals)
    B.to_html(os.environ["HOME_DIR"] + "/www/index.html")


if __name__ == "__main__":
    update_html()
