"""Dev helper: contact sheet of images. Usage: imgsheet.py out.png cols thumbW img1 img2 ..."""
import sys
from PIL import Image

out, cols, tw, *files = sys.argv[1:]
cols, tw = int(cols), int(tw)
ims = [Image.open(f).convert('RGB') for f in files]
th = int(tw * ims[0].height / ims[0].width)
rows = (len(ims) + cols - 1) // cols
sheet = Image.new('RGB', (cols * tw, rows * th), 'black')
for i, im in enumerate(ims):
    sheet.paste(im.resize((tw, th)), ((i % cols) * tw, (i // cols) * th))
sheet.save(out)
