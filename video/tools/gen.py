import base64, os, sys, pathlib
from openai import OpenAI
out = pathlib.Path(sys.argv[1]); pose = sys.argv[2]; n = int(sys.argv[3])
client = OpenAI(api_key=os.environ["MODEL_API_KEY"], base_url="https://api.meta.ai/v1")
base = ("Adorable 3D animated-film style character, full body, standing, centered: a young Indian woman who is a "
        "category manager. Shoulder-length straight black hair that ends just at her shoulders, with a soft side part, clear transparent "
        "rectangular glasses with thin rose-gold frames, small pearl stud earrings, big friendly sparkling eyes, "
        "rosy cheeks, warm gentle smile. Wearing a black button-up shirt, dark blue jeans and bright orange sneakers. ")
prompt = base + pose + (" Isolated on a plain solid flat pale grey background, soft studio lighting, "
                        "Pixar-like charm, highly detailed, no text, no logo.")
for i in range(n):
    r = client.images.generate(model="muse-image-1.0", prompt=prompt, size="1024x1024", extra_body={"output_format": "png"})
    p = out / f"{pose.split()[0].lower()}-{i}.png"
    p.write_bytes(base64.b64decode(r.data[0].b64_json)); print(p)
