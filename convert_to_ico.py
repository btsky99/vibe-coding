from PIL import Image
import sys

def convert_to_ico(input_path, output_path):
    img = Image.open(input_path).convert("RGBA")
    
    # Crop to content box
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
        
    # Make it square
    w, h = img.size
    max_dim = max(w, h)
    new_img = Image.new('RGBA', (max_dim, max_dim), (0, 0, 0, 0))
    new_img.paste(img, ((max_dim - w) // 2, (max_dim - h) // 2))
    img = new_img
    
    img.save(output_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"Successfully saved clean ICO to {output_path}")

if __name__ == "__main__":
    convert_to_ico(sys.argv[1], sys.argv[2])
