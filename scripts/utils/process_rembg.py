from rembg import remove
from PIL import Image
import sys

def remove_bg(input_path, output_path):
    print("Removing background using AI...")
    input = Image.open(input_path)
    output = remove(input)
    output.save(output_path)
    print("AI Background removal complete.")

if __name__ == "__main__":
    remove_bg(sys.argv[1], sys.argv[2])
