import os
from pathlib import Path

import matplotlib.image as mpimg
import matplotlib.pyplot as plt

from avo_alarms.utils import plotting
from avo_alarms.utils.setup_utils import TMP_DIR


def plot_fig(config):

    plt.figure(figsize=(3, 4.4))

    img_file_name = TMP_DIR / "sacs_out_.png"
    tmp_file1 = Path(str(img_file_name).replace(".png", "1.png"))
    tmp_file2 = Path(str(img_file_name).replace(".png", "2.png"))
    img1 = mpimg.imread(tmp_file1)
    img2 = mpimg.imread(tmp_file2)

    plt.subplot(2, 1, 1)
    plt.imshow(img1)
    plt.gca().set_xticks([])
    plt.gca().set_yticks([])

    plt.subplot(2, 1, 2)
    plt.imshow(img2)
    plt.gca().set_xticks([])
    plt.gca().set_yticks([])

    plt.tight_layout(pad=0.5)

    jpg_file = plotting.save_file(plt, config, dpi=500)

    os.remove(tmp_file1)
    os.remove(tmp_file2)

    return jpg_file
