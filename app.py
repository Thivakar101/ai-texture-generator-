# -*- coding: utf-8 -*-
"""
Flask application for generating high-quality images using Google Vertex AI Imagen API via REST requests.
Enhanced version with professional styles and advanced parameters.
"""

import base64
import io
import json
import os
import uuid
import traceback
import datetime
from pathlib import Path
import random

import google.auth
import google.auth.transport.requests
import requests
from flask import Flask, flash, redirect, render_template, request, url_for, jsonify
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------- #
#                              Configuration                                   #
# ---------------------------------------------------------------------------- #

# --- Google Cloud Configuration ---
PROJECT_ID = "spring-firefly-397302"  # YOUR Google Cloud Project ID - CHANGE IF NEEDED
LOCATION = "us-central1"      # Region for Imagen model - CHANGE IF NEEDED
# Model ID for advanced image generation
MODEL_ID = "imagen-3.0-generate-002"

# Construct the REST API prediction endpoint URL
API_ENDPOINT = (
    f"https://{LOCATION}-aiplatform.googleapis.com/v1/projects/{PROJECT_ID}"
    f"/locations/{LOCATION}/publishers/google/models/{MODEL_ID}:predict"
)

# --- Flask App Setup ---
app = Flask(__name__)
# Secret key for session management (used for flash messages)
app.secret_key = os.urandom(24)

# --- File Upload Configuration ---
# Use relative paths for portability within the project structure
STATIC_FOLDER = os.path.join(os.path.dirname(__file__), 'static')
GENERATED_FOLDER = os.path.join(STATIC_FOLDER, 'generated')

app.config['GENERATED_FOLDER'] = GENERATED_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # Limit uploads to 16MB

# Ensure generated directory exists
os.makedirs(GENERATED_FOLDER, exist_ok=True)


# ---------------------------------------------------------------------------- #
#                       Authentication Helper                                  #
# ---------------------------------------------------------------------------- #

# Cache credentials globally to avoid re-fetching on every request
_GOOGLE_AUTH_CREDENTIALS = None
_GOOGLE_AUTH_PROJECT = None

def get_access_token():
    """
    Fetches or refreshes an OAuth 2.0 access token using Application Default Credentials (ADC).

    ADC automatically finds credentials from:
    1. GOOGLE_APPLICATION_CREDENTIALS environment variable (service account key).
    2. gcloud application-default login credentials (user credentials).
    3. App Engine / Cloud Run / Compute Engine built-in service accounts.

    Returns:
        str: A valid OAuth 2.0 access token, or None if fetching fails.
    """
    global _GOOGLE_AUTH_CREDENTIALS, _GOOGLE_AUTH_PROJECT
    try:
        # Check if credentials exist and are still valid (or nearing expiry)
        if not _GOOGLE_AUTH_CREDENTIALS or not _GOOGLE_AUTH_CREDENTIALS.valid:
            print("Fetching/Refreshing Google credentials...")
            scopes = ['https://www.googleapis.com/auth/cloud-platform']
            _GOOGLE_AUTH_CREDENTIALS, _GOOGLE_AUTH_PROJECT = google.auth.default(scopes=scopes)

            # Ensure credentials object supports refresh (e.g., user creds, service account)
            if hasattr(_GOOGLE_AUTH_CREDENTIALS, 'refresh'):
                 auth_req = google.auth.transport.requests.Request()
                 _GOOGLE_AUTH_CREDENTIALS.refresh(auth_req)
                 print("Credentials refreshed.")
            elif not _GOOGLE_AUTH_CREDENTIALS.token:
                 # Handle cases like metadata server where token might not be present initially
                 print("Warning: Credentials obtained but token missing initially. May need explicit fetch depending on environment.")

        # Validate that we have a token after attempting fetch/refresh
        if not _GOOGLE_AUTH_CREDENTIALS or not _GOOGLE_AUTH_CREDENTIALS.token:
             print("Error: Failed to obtain access token from credentials.")
             # Add more specific checks or attempts if needed based on credential type
             return None

        # Successfully obtained or refreshed token
        return _GOOGLE_AUTH_CREDENTIALS.token

    except google.auth.exceptions.RefreshError as e:
        print(f"ERROR refreshing credentials: {e}")
        print("Credentials might have expired or been revoked.")
        print("Try running 'gcloud auth application-default login' again if using user credentials.")
        _GOOGLE_AUTH_CREDENTIALS = None # Force re-fetch next time
        return None
    except google.auth.exceptions.DefaultCredentialsError as e:
        print("--------------------------------------------------------------")
        print("ERROR: Authentication failed. Could not find default credentials.")
        print("Ensure you have configured authentication:")
        print(f"1. User: Run `gcloud auth application-default login` AND `gcloud auth application-default set-quota-project {PROJECT_ID}`")
        print("2. Service Account: Set the GOOGLE_APPLICATION_CREDENTIALS environment variable to the path of your service account key file.")
        print(f"Details: {e}")
        print("--------------------------------------------------------------")
        return None
    except Exception as e:
        print(f"ERROR: Unexpected error getting access token: {e}")
        traceback.print_exc()
        return None


# ---------------------------------------------------------------------------- #
#                        Vertex AI API Calls (Requests)                        #
# ---------------------------------------------------------------------------- #

def generate_image_requests(prompt, negative_prompt=None, style_preset=None, aspect_ratio="1:1", quality="standard"):
    """
    Generates an image from a text prompt using the Vertex AI REST API with enhanced parameters.

    Args:
        prompt (str): The text prompt for image generation.
        negative_prompt (str, optional): Elements to avoid in the generation.
        style_preset (str, optional): Style preset to apply (photographic, digital-art, etc.)
        aspect_ratio (str, optional): Desired aspect ratio for the generated image.
        quality (str, optional): Image quality setting (standard, hd)

    Returns:
        dict: A dictionary containing 'image_url' on success, or 'error' on failure.
    """
    access_token = get_access_token()
    if not access_token:
        return {"error": "Failed to get access token. Check server logs."}

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    
    # Configure parameters based on inputs
    instance = {"prompt": prompt}
    if negative_prompt:
        instance["negative_prompt"] = negative_prompt
        
    # Initialize parameters dictionary with sampleCount
    parameters = {"sampleCount": 1}
    
    # Set image quality parameters
    quality_params = {
        "standard": {"steps": 30},
        "hd": {"steps": 50}
    }
    
    # Apply quality settings if available
    if quality in quality_params:
        parameters.update(quality_params[quality])
    
    # Map aspect ratio to dimensions
    aspect_dimensions = {
        "1:1": {"height": 1024, "width": 1024},  # Square
        "16:9": {"height": 576, "width": 1024},  # Landscape
        "9:16": {"height": 1024, "width": 576},  # Portrait
        "4:3": {"height": 768, "width": 1024},   # Standard
        "3:4": {"height": 1024, "width": 768},   # Vertical
        "21:9": {"height": 448, "width": 1024},  # Ultrawide
    }
    
    # Debug log to see if aspect ratio is being correctly identified
    print(f"Selected aspect ratio: {aspect_ratio}")
    
    # Add dimensions if a valid aspect ratio was selected
    if aspect_ratio in aspect_dimensions:
        print(f"Using dimensions for aspect ratio {aspect_ratio}: {aspect_dimensions[aspect_ratio]}")
        parameters["height"] = aspect_dimensions[aspect_ratio]["height"]
        parameters["width"] = aspect_dimensions[aspect_ratio]["width"]
    else:
        # Default to square if aspect ratio is not recognized
        print(f"Warning: Unrecognized aspect ratio '{aspect_ratio}', defaulting to 1:1")
        parameters["height"] = 1024
        parameters["width"] = 1024
    
    # Apply guidance scale based on style preset
    guidance_scales = {
        "photographic": 6.0,
        "digital-art": 7.5,
        "cinematic": 7.0,
        "anime": 7.0,
        "fantasy-art": 8.0,
        "neon-punk": 8.5,
        "enhance": 5.5,
        "comic-book": 7.5,
        "isometric": 7.0,
        "low-poly": 7.0,
        "origami": 7.5,
        "line-art": 7.0,
        "watercolor": 6.5,
        "pixel-art": 8.0
    }
    
    # Add style-specific guidance scale if style was selected
    if style_preset in guidance_scales:
        parameters["guidance_scale"] = guidance_scales[style_preset]
        # Some styles benefit from style prefixing in prompt
        style_prefixes = {
            "digital-art": "digital art style",
            "cinematic": "cinematic lighting",
            "anime": "anime style",
            "fantasy-art": "fantasy art",
            "neon-punk": "neon cyberpunk style",
            "comic-book": "comic book style",
            "isometric": "isometric view",
            "low-poly": "low poly 3D",
            "origami": "origami style",
            "line-art": "line art",
            "watercolor": "watercolor painting",
            "pixel-art": "pixel art"
        }
        
        # Enhance prompt with style prefix if applicable
        if style_preset in style_prefixes and not style_prefixes[style_preset].lower() in prompt.lower():
            instance["prompt"] = f"{prompt}, {style_prefixes[style_preset]}"
    else:
        # Default guidance scale
        parameters["guidance_scale"] = 7.0
    
    # Complete payload for text-to-image generation
    data = {
        "instances": [instance],
        "parameters": parameters
    }

    print(f"Sending GENERATE request to: {API_ENDPOINT}")
    print(f"Generation parameters: Prompt='{prompt}', Style='{style_preset}', Aspect={aspect_ratio}, Quality={quality}")
    print(f"Full request data: {json.dumps(data, indent=2)}")
    
    try:
        response = requests.post(API_ENDPOINT, headers=headers, data=json.dumps(data), timeout=180)
        print(f"GENERATE Response Status Code: {response.status_code}")
        response.raise_for_status() # Raise HTTPError for 4xx/5xx responses

        try:
            response_json = response.json()
            # Optional: Print the full successful response for debugging
            print(f"Full GENERATE Response JSON (Status {response.status_code}): {json.dumps(response_json, indent=2)}")
        except json.JSONDecodeError:
            print(f"ERROR: Could not decode JSON from GENERATE response (Status {response.status_code}). Text: {response.text}")
            return {"error": "API returned OK status but response was not valid JSON."}

        # Process successful response
        if 'predictions' not in response_json or not response_json['predictions']:
            print("API Error: 'predictions' key missing or empty in GENERATE response.")
            
            # Check for safety filtering
            if 'safetyAttributes' in response_json:
                safety_attrs = response_json.get('safetyAttributes', {})
                filtered = safety_attrs.get('filtered', False)
                reasons = safety_attrs.get('reason', 'Unknown')
                if filtered:
                    error_msg = f"Generation blocked by safety filters (Reason: {reasons}). Please modify your prompt."
                    return {"error": error_msg}
            
            return {"error": "API did not return predictions. Check logs."}
            
        try:
            # Expecting Base64 encoded image string
            image_b64_data = response_json['predictions'][0]['bytesBase64Encoded']
        except (KeyError, IndexError, TypeError) as e:
            print(f"ERROR extracting GENERATE image data from JSON path ['predictions'][0]['bytesBase64Encoded']: {e}")
            print(f"Response JSON structure: {json.dumps(response_json, indent=2)}")
            return {"error": "Failed to parse expected image data from API response."}

        # Decode and save the generated image
        unique_filename = f"generated_{uuid.uuid4()}.png"
        output_path = os.path.join(app.config['GENERATED_FOLDER'], unique_filename)
        try:
            image_bytes = base64.b64decode(image_b64_data)
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            print(f"Generated image saved successfully to {output_path}")
            image_url = url_for('static', filename=f'generated/{unique_filename}')
            
            # Record image metadata for gallery
            save_image_metadata(unique_filename, prompt, "generation", {
                "style_preset": style_preset,
                "aspect_ratio": aspect_ratio,
                "quality": quality
            })
            
            return {"image_url": image_url}  # Success
        except (base64.binascii.Error, TypeError, IOError) as e:
            print(f"ERROR decoding/saving generated image data: {e}")
            return {"error": f"Failed to decode or save generated image: {e}"}

    # --- Handle Specific Request/HTTP Errors ---
    except requests.exceptions.Timeout:
        print(f"ERROR: GENERATE request timed out.")
        return {"error": "Image generation request timed out."}
    except requests.exceptions.HTTPError as e:
        print(f"ERROR: HTTP Error during GENERATE: {e}")
        error_details = f"HTTP {e.response.status_code}"
        try: # Attempt to parse error details from JSON response
            err_json = e.response.json()
            error_details += f": {err_json.get('error', {}).get('message', e.response.text)}"
            print(f"Response error JSON: {json.dumps(err_json, indent=2)}")
        except json.JSONDecodeError: # Fallback to raw text if not JSON
            error_details += f": {e.response.text}"
            print(f"Response error text: {e.response.text}")
        return {"error": error_details}
    except requests.exceptions.RequestException as e:
        # Catch other network-related errors (DNS, connection, etc.)
        print(f"ERROR: GENERATE request failed (Network): {e}")
        return {"error": f"Network or request error during generation: {e}"}
    except Exception as e:
        # Catch-all for other unexpected errors during the process
        print(f"ERROR: Unexpected error during generation: {e}")
        traceback.print_exc()
        return {"error": f"An unexpected server error occurred during generation: {e}"}


# ---------------------------------------------------------------------------- #
#                             Utility Functions                                #
# ---------------------------------------------------------------------------- #

def save_image_metadata(filename, prompt, operation_type, extra_params=None):
    """
    Saves metadata about a generated image for use in the gallery.
    
    Args:
        filename (str): The filename of the saved image
        prompt (str): The prompt used to generate the image
        operation_type (str): Type of operation (generation)
        extra_params (dict, optional): Additional parameters to store
    """
    metadata_path = os.path.join(app.config['GENERATED_FOLDER'], 'metadata.json')
    
    # Load existing metadata if available
    metadata = []
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
        except (json.JSONDecodeError, IOError):
            # If file is corrupted or can't be read, start fresh
            metadata = []
    
    # Add new entry
    entry = {
        'filename': filename,
        'prompt': prompt,
        'type': operation_type,
        'created': datetime.datetime.now().isoformat()
    }
    
    # Add extra parameters if provided
    if extra_params:
        entry.update(extra_params)
    
    metadata.append(entry)
    
    # Save updated metadata
    try:
        with open(metadata_path, 'w') as f:
            json.dump(metadata, f, indent=2)
    except IOError as e:
        print(f"WARNING: Could not save image metadata: {e}")


def get_gallery_images():
    """
    Gets the list of available generated images with metadata.
    
    Returns:
        list: List of image information dictionaries
    """
    metadata_path = os.path.join(app.config['GENERATED_FOLDER'], 'metadata.json')
    
    # If we have metadata, use it
    if os.path.exists(metadata_path):
        try:
            with open(metadata_path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            print(f"WARNING: Could not load gallery metadata: {e}")
    
    # Otherwise build basic list from files
    result = []
    generated_dir = Path(app.config['GENERATED_FOLDER'])
    
    try:
        for img_path in generated_dir.glob('*.png'):
            if img_path.is_file() and not img_path.name.startswith('.'):
                # Get file stats 
                stats = img_path.stat()
                result.append({
                    'filename': img_path.name,
                    'prompt': 'Unknown',
                    'type': 'generated',
                    'created': datetime.datetime.fromtimestamp(stats.st_ctime).isoformat()
                })
    except Exception as e:
        print(f"ERROR listing gallery images: {e}")
        traceback.print_exc()
        
    return result


# ---------------------------------------------------------------------------- #
#                                Flask Routes                                  #
# ---------------------------------------------------------------------------- #

@app.route('/', methods=['GET'])
def index():
    """Renders the main HTML page."""
    return render_template('index.html', generation_result=None)


@app.route('/generate', methods=['POST'])
def handle_generate():
    """Handles POST requests for text-to-image generation."""
    generation_result = None # Initialize result dictionary
    prompt = request.form.get('prompt')
    negative_prompt = request.form.get('negative_prompt')
    aspect_ratio = request.form.get('aspect_ratio', '1:1')
    style_preset = request.form.get('style_preset', '')
    quality = request.form.get('quality', 'standard')
    
    # Debug logs - check the form values received from the frontend
    print(f"Form data received: prompt='{prompt}', aspect_ratio='{aspect_ratio}', style_preset='{style_preset}', quality='{quality}'")
    
    if not prompt:
        flash('Prompt is required for generation!', 'error')
        generation_result = {"error": "Prompt is required"}
    else:
        print(f"Received generation request with prompt: '{prompt}'")
        # Call the API function with all parameters
        generation_result = generate_image_requests(
            prompt=prompt,
            negative_prompt=negative_prompt,
            style_preset=style_preset if style_preset else None,
            aspect_ratio=aspect_ratio,
            quality=quality
        )
        # Flash error message if API call failed
        if generation_result.get("error") and not generation_result.get("image_url"):
            flash(f"Generation failed: {generation_result['error']}", 'error')
        elif generation_result.get("image_url"):
            flash("Image generated successfully!", 'success')

    # Re-render the main page, passing the result (image URL or error)
    return render_template('index.html', generation_result=generation_result)


@app.route('/static/generated', methods=['GET'])
def get_gallery():
    """API endpoint to get the list of generated images for the gallery."""
    images = get_gallery_images()
    return jsonify({'images': images})


@app.route('/api/gallery/delete/<filename>', methods=['POST'])
def delete_image(filename):
    """Deletes an image from the gallery."""
    if not filename:
        return jsonify({'success': False, 'error': 'No filename provided'}), 400
    
    filename = secure_filename(filename)  # Sanitize the filename
    file_path = os.path.join(app.config['GENERATED_FOLDER'], filename)
    
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': 'File not found'}), 404
    
    try:
        os.remove(file_path)
        # Also update metadata
        metadata_path = os.path.join(app.config['GENERATED_FOLDER'], 'metadata.json')
        if os.path.exists(metadata_path):
            try:
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                
                # Remove the entry for the deleted file
                metadata = [item for item in metadata if item.get('filename') != filename]
                
                with open(metadata_path, 'w') as f:
                    json.dump(metadata, f, indent=2)
            except (json.JSONDecodeError, IOError):
                pass  # Ignore metadata issues
                
        return jsonify({'success': True}), 200
    except Exception as e:
        print(f"ERROR: Failed to delete image {filename}: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


# ---------------------------------------------------------------------------- #
#                                Main Execution                                #
# ---------------------------------------------------------------------------- #

if __name__ == '__main__':
    print("-" * 60)
    print("Starting Flask Advanced Image Generation App...")
    print(f"Google Cloud Project ID: {PROJECT_ID}")
    print(f"Location (Region):       {LOCATION}")
    print(f"Vertex AI Model ID:      {MODEL_ID}")
    print(f"API Endpoint:            {API_ENDPOINT}")
    print("-" * 60)
    print("Ensure Google Cloud Authentication is configured:")
    print(" - User Credentials: Run `gcloud auth application-default login`")
    print(f" - Set Quota Project: Run `gcloud auth application-default set-quota-project {PROJECT_ID}`")
    print(" - Service Account: Set GOOGLE_APPLICATION_CREDENTIALS environment variable.")
    print("-" * 60)
    
    # Enable the gallery functionality
    print("Initializing gallery functionality...")
    if not os.path.exists(os.path.join(app.config['GENERATED_FOLDER'], 'metadata.json')):
        print("Creating initial metadata.json file for gallery")
        existing_images = get_gallery_images()
        with open(os.path.join(app.config['GENERATED_FOLDER'], 'metadata.json'), 'w') as f:
            json.dump(existing_images, f, indent=2)
    
    print("-" * 60)
    # Run the Flask development server
    # Set debug=False for production environments!
    app.run(debug=True, host='0.0.0.0', port=5001)