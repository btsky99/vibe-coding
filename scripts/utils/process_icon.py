from PIL import Image
import sys

def process_image(input_path, output_path):
    # Open the image
    img = Image.open(input_path).convert("RGBA")
    
    pixels = img.load()
    width, height = img.size
    
    # Helper to check if a pixel is "black-ish"
    def is_black(p):
        return p[0] < 30 and p[1] < 30 and p[2] < 30 and p[3] > 0
    
    # We will do a simple BFS (flood fill) from all edges to find background black pixels
    # and turn them transparent.
    visited = set()
    queue = []
    
    # Add all edge pixels
    for x in range(width):
        queue.append((x, 0))
        queue.append((x, height - 1))
    for y in range(height):
        queue.append((0, y))
        queue.append((width - 1, y))
        
    while queue:
        x, y = queue.pop(0)
        
        if (x, y) in visited:
            continue
            
        if x < 0 or x >= width or y < 0 or y >= height:
            continue
            
        visited.add((x, y))
        
        p = pixels[x, y]
        if is_black(p):
            pixels[x, y] = (0, 0, 0, 0) # Make it transparent
            # Add neighbors
            queue.append((x+1, y))
            queue.append((x-1, y))
            queue.append((x, y+1))
            queue.append((x, y-1))

    # Now let's crop to the non-transparent bounding box
    bbox = img.getbbox()
    if bbox:
        img = img.crop(bbox)
        
    # Make it square if it's not (add padding)
    w, h = img.size
    max_dim = max(w, h)
    new_img = Image.new('RGBA', (max_dim, max_dim), (0, 0, 0, 0))
    new_img.paste(img, ((max_dim - w) // 2, (max_dim - h) // 2))
    img = new_img
    
    # Save as ICO with multiple sizes
    img.save(output_path, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
    print(f"Successfully saved to {output_path}")

if __name__ == "__main__":
    process_image(sys.argv[1], sys.argv[2])
