import os
import datetime # Ensure datetime is imported
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from google.cloud import storage
from dotenv import load_dotenv
import logging

# --- Configuration ---
load_dotenv()
logging.basicConfig(level=logging.INFO)
SERVICE_ACCOUNT_KEY_PATH = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

if not SERVICE_ACCOUNT_KEY_PATH or not BUCKET_NAME:
    logging.error("Error: GOOGLE_APPLICATION_CREDENTIALS or GCS_BUCKET_NAME not set in .env")
    exit(1)

# --- Initialize Flask App and GCS Client ---
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

try:
    storage_client = storage.Client.from_service_account_json(SERVICE_ACCOUNT_KEY_PATH)
    bucket = storage_client.bucket(BUCKET_NAME)
    logging.info(f"Successfully connected to GCS bucket: {BUCKET_NAME}")
except FileNotFoundError:
    logging.error(f"Error: Service account key file not found at {SERVICE_ACCOUNT_KEY_PATH}")
    exit(1)
except Exception as e:
    logging.error(f"Error initializing Google Cloud Storage client: {e}")
    exit(1)

# --- API Routes ---

@app.route('/')
def serve_index():
    """Serves the index.html file."""
    return send_from_directory('.', 'index.html')

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handles image uploads to GCS (privately)."""
    if 'image' not in request.files:
        return jsonify({"error": "No image file part in the request"}), 400

    file = request.files['image']

    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400

    if file:
        try:
            # Consider adding a unique prefix (like UUID) to prevent overwrites
            blob_name = file.filename
            blob = bucket.blob(blob_name)

            # Upload the file stream
            blob.upload_from_file(file.stream, content_type=file.content_type)
            logging.info(f"File {blob_name} uploaded successfully to {BUCKET_NAME} (privately).")

            # --- No longer attempting to make public ---
            # File is uploaded privately. Access is granted via Signed URLs when requested.

            # Return success message without a permanent URL
            return jsonify({
                "message": f"File '{blob_name}' uploaded successfully (privately).",
                "filename": blob_name,
                "url": None # Explicitly state no persistent URL is available here
            }), 201 # 201 Created

        except Exception as e:
            logging.error(f"Error uploading file to GCS: {e}")
            return jsonify({"error": f"Failed to upload file: {e}"}), 500
    else:
        return jsonify({"error": "An unexpected error occurred"}), 500

@app.route('/api/images', methods=['GET'])
def get_image_urls():
    """Retrieves Signed URLs for accessing images."""
    urls = []
    try:
        blobs = bucket.list_blobs()
        for blob in blobs:
            try:
                # Generate a signed URL valid for 15 minutes (adjust as needed)
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=15), # URL expires in 15 mins
                    method="GET" # Allow reading the object
                )
                urls.append(signed_url)
            except Exception as e_sign:
                # Log error if signing fails (e.g., missing Service Account Token Creator role)
                logging.error(f"Could not generate signed URL for {blob.name}: {e_sign}. Check IAM permissions.")
                # Optionally append a placeholder or skip this blob
                # urls.append(None) # Or just skip by doing nothing here

        return jsonify(urls), 200
    except Exception as e:
        logging.error(f"Error listing blobs or generating URLs: {e}")
        return jsonify({"error": f"Failed to retrieve image URLs: {e}"}), 500


@app.route('/api/list-images', methods=['GET'])
def list_image_metadata():
    """Retrieves metadata including a Signed URL for access."""
    image_info_list = []
    try:
        blobs = bucket.list_blobs()
        for blob in blobs:
            signed_url = None # Initialize url as None for each blob
            try:
                # Generate a signed URL valid for 15 minutes
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=15),
                    method="GET"
                )
            except Exception as e_sign:
                logging.error(f"Could not generate signed URL for {blob.name} in metadata list: {e_sign}. Check IAM permissions.")
                # Keep signed_url as None if generation fails

            # Add metadata to the list, including the signed URL (which might be None if signing failed)
            image_info_list.append({
                "name": blob.name,
                "filename": blob.name,
                "url": signed_url, # Use the generated (or None) Signed URL
                "size": blob.size,
                "updated": blob.updated.isoformat() if blob.updated else None
            })

        # Note: The frontend JS should ideally check if the url is valid before using it
        return jsonify(image_info_list), 200
    except Exception as e:
        logging.error(f"Error listing blob metadata: {e}")
        return jsonify({"error": f"Failed to retrieve image list: {e}"}), 500


# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)