"""One-off: turns the finished signature banner into a template with the name, position, phone, email and photo taken out.
Usage: python make_sig_template.py Final.png   ->  sig_template.png"""
import sys
import cv2
import numpy as np

src = cv2.imread(sys.argv[1], cv2.IMREAD_UNCHANGED)
if src.shape[2] == 4:
    a = src[:, :, 3:4] / 255.0
    src = (src[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
h, w = src.shape[:2]
img = src.copy()
# 1) photo: the slanted strip on the left becomes plain grey (the program draws the user's photo there)
poly = np.array([[0, 0], [344, 0], [266, h], [0, h]], np.int32)
cv2.fillPoly(img, [poly], (217, 217, 217))
# 2) text that the user changes: name, position, phone line, email line (the icons and the website stay)
boxes = [(846, 120, 1160, 170), (846, 176, 1040, 208), (888, 232, 1200, 268), (1262, 232, 1600, 268)]
mask = np.zeros((h, w), np.uint8)
gray = cv2.cvtColor(src, cv2.COLOR_BGR2GRAY)
for x0, y0, x1, y1 in boxes:
    sub = src[y0:y1, x0:x1].astype(int)
    dark = (sub.sum(axis=2) < 560)                                  # black or red strokes
    redish = (sub[:, :, 2] - sub[:, :, 0]) > 60
    m = (dark | redish).astype(np.uint8) * 255
    mask[y0:y1, x0:x1] = m
mask = cv2.dilate(mask, np.ones((5, 5), np.uint8), iterations=2)
img = cv2.inpaint(img, mask, 6, cv2.INPAINT_TELEA)
cv2.imwrite(sys.argv[2] if len(sys.argv) > 2 else "sig_template.png", img)
