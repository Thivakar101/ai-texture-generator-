import requests
import json
import google.auth
import google.auth.transport.requests
import base64 # Needed if image is base64 encoded
from flask import Flask, request, jsonify
import os

# Replace with your actual project ID and location
PROJECT_ID = "spring-firefly-397302"  # Your Project ID
LOCATION = "us-central1"  # Or the region where Imagen 3 is available

# Verify this Model ID is correct and available in your project/location
MODEL_ID = "imagen-3.0-generate-002" # Example ID - VERIFY THIS
API_ENDPOINT = f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}/locations/{LOCATION}/publishers/google/models/{MODEL_ID}:predict"

def get_access_token():
    """Fetches an OAuth 2.0 access token using Application Default Credentials."""
    try:
        # Scopes required for Vertex AI Prediction
        scopes = ['https://www.googleapis.com/auth/cloud-platform']
        credentials, project = google.auth.default(scopes=scopes)

        # Create an authorized session object or refresh the credentials
        auth_req = google.auth.transport.requests.Request()
        credentials.refresh(auth_req) # Refresh credentials to get the token

        if not credentials.token:
            print("Error: Failed to obtain access token from credentials.")
            return None

        print("Successfully obtained access token.")
        return credentials.token
    except google.auth.exceptions.DefaultCredentialsError as e:
        print("--------------------------------------------------------------")
        print("Error: Authentication failed. Could not find default credentials.")
        print("Please run 'gcloud auth application-default login' in your terminal.")
        print(f"Details: {e}")
        print("--------------------------------------------------------------")
        return None
    except Exception as e:
        print(f"Error getting access token: {e}")
        return None


def generate_image_requests(prompt, output_filename="generated_image_req.png"):
    """
    Generates an image from a text prompt using the Imagen 3 API via requests.
    """
    access_token = get_access_token()
    if not access_token:
        print("Failed to get access token. Aborting generation.")
        return None

    headers = {
        "Authorization": f"Bearer {access_token}", # Use the obtained token
        "Content-Type": "application/json"
    }

    # Request body structure for Vertex AI prediction endpoint
    # Adjust parameters based on Imagen 3 documentation
    data = {
        "instances": [
            {
                # The exact field name might vary slightly (e.g., 'text', 'prompt')
                # Check Imagen 3 documentation for the :predict endpoint
                "prompt": prompt
            }
        ],
        "parameters": {
            # Add specific Imagen 3 parameters here
            # Example: "sampleCount": 1 # Often controls number of images
            # Example: "aspectRatio": "1:1"
            # Example: "negativePrompt": "text, words, blurry"
        }
    }

    print(f"Sending request to: {API_ENDPOINT}")
    try:
        response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(data), timeout=120) # Increased timeout
        # Always check status code *before* trying to decode JSON
        print(f"Response Status Code: {response.status_code}")
        response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

        response_json = response.json()
        print(f"Full API Response JSON: {json.dumps(response_json, indent=2)}") # Pretty print

        # Check for errors *within* the JSON response (sometimes status is 200 but there's an error field)
        if 'error' in response_json:
            error_message = response_json['error'].get('message', 'Unknown API error in JSON')
            print(f"API Error in Response: {error_message}")
            return None

        # --- CRITICAL: Extract Image Data ---
        try:
            # Try different possible paths for the image data
            if 'predictions' in response_json and response_json['predictions']:
                if isinstance(response_json['predictions'][0], dict):
                    if 'bytesBase64Encoded' in response_json['predictions'][0]:
                        image_b64_data = response_json['predictions'][0]['bytesBase64Encoded']
                    elif 'imageBytes' in response_json['predictions'][0]:
                        image_b64_data = response_json['predictions'][0]['imageBytes']
                    elif 'image' in response_json['predictions'][0] and isinstance(response_json['predictions'][0]['image'], dict):
                        image_b64_data = response_json['predictions'][0]['image'].get('bytesBase64Encoded')
                    else:
                        # The prediction might directly be the base64 string
                        image_b64_data = response_json['predictions'][0]
                else:
                    # In case the prediction is directly the base64 string
                    image_b64_data = response_json['predictions'][0]
            else:
                raise KeyError("Could not find 'predictions' key in response")
                
            print("Successfully extracted image data.")
        except (KeyError, IndexError, TypeError) as e:
            print(f"Error extracting image data from response: {e}")
            print("Please inspect the 'Full API Response JSON' above and update the extraction logic.")
            return None

        # Decode base64 and process the image to ensure it's rectangular with no gaps
        try:
            import io
            from PIL import Image
            import numpy as np
            
            # Decode base64 to image
            image_bytes = base64.b64decode(image_b64_data)
            image_stream = io.BytesIO(image_bytes)
            image = Image.open(image_stream)
            
            # Convert to RGBA to handle transparency
            if image.mode != "RGBA":
                image = image.convert("RGBA")
            
            # Create a new opaque background image
            width, height = image.size
            background = Image.new("RGBA", (width, height), (255, 255, 255, 255))
            
            # Composite the potentially transparent image onto the solid background
            composite = Image.alpha_composite(background, image)
            
            # Convert back to RGB (removing alpha channel)
            final_image = composite.convert("RGB")
            
            # Save the image
            final_image.save(output_filename, format="PNG")
            print(f"Image successfully processed and saved as a full rectangle to {output_filename}")
            return output_filename # Return filename on success
        except Exception as e:
            print(f"Error processing image: {e}")
            return None

    except requests.exceptions.Timeout:
        print(f"Error: API request timed out after 120 seconds.")
        return None
    except requests.exceptions.HTTPError as e:
        # This catches errors raised by response.raise_for_status() (4xx, 5xx)
        print(f"Error: HTTP Error occurred: {e}")
        print(f"Response status code: {e.response.status_code}")
        # Try to print error details from response body if possible
        try:
            error_details = e.response.json()
            print(f"Response error JSON: {json.dumps(error_details, indent=2)}")
        except json.JSONDecodeError:
            print(f"Response error text: {e.response.text}") # Fallback to raw text
        return None
    except requests.exceptions.RequestException as e:
        # Catches other network/request related errors (DNS, connection refused, etc.)
        print(f"Error: API request failed: {e}")
        return None
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON response: {e}")
        if 'response' in locals() and response is not None:
             print(f"Raw response text that failed to parse: {response.text}")
        return None


app = Flask(__name__)

@app.route('/')
def index():
    return "Flask server is running. Use the /generate_texture endpoint to generate textures."

@app.route('/generate_texture', methods=['POST'])
def generate_texture():
    data = request.get_json()
    prompt = data.get('prompt')
    output_filename = data.get('output_filename')

    if not prompt or not output_filename:
        return jsonify({"error": "Missing 'prompt' or 'output_filename' in request."}), 400

    # Validate the output_filename to ensure it is a valid file path
    if not output_filename.endswith('.png') or any(c in output_filename for c in "<>:\"/\\|?*"):
        return jsonify({"error": "Invalid output filename."}), 400

    # Enhance prompt to ensure full rectangular texture with no rounded corners or gaps
    enhanced_prompt = f"{prompt}, seamless tileable texture, full rectangular format, no rounded corners, no borders, no black spaces, no gaps, filling entire frame, high-resolution, flat texture"
    
    # Ensure the output directory exists
    output_dir = os.path.join(os.path.dirname(__file__), "generated")
    os.makedirs(output_dir, exist_ok=True)
    output_filepath = os.path.join(output_dir, output_filename)

    # Call the generate_image_requests function with enhanced prompt
    saved_file = generate_image_requests(enhanced_prompt, output_filepath)

    if saved_file:
        return jsonify({"file_path": os.path.abspath(saved_file)})
    else:
        return jsonify({"error": "Failed to generate texture."}), 500

if __name__ == "__main__":
    print("Starting Flask server on http://127.0.0.1:5000/")
    app.run(host="127.0.0.1", port=5000, debug=False)  # Disabled debug mode