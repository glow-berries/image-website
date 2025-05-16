import os
import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from google.cloud import storage
import logging
import sys
from dotenv import load_dotenv
load_dotenv()

FRONTEND_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))

# --- Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# Read GCS_BUCKET_NAME from environment variable
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

if not BUCKET_NAME:
    logger.error("CRITICAL ERROR: GCS_BUCKET_NAME environment variable not set.")
    sys.exit("GCS_BUCKET_NAME environment variable is required.")

# --- Initialize Flask App and GCS Client ---
app = Flask(__name__, static_folder=FRONTEND_FOLDER, static_url_path='')
CORS(app)

try:
    storage_client = storage.Client()
    bucket = storage_client.bucket(BUCKET_NAME)
    logger.info(f"Successfully connected to GCS bucket: {BUCKET_NAME} using GOOGLE_APPLICATION_CREDENTIALS.")
except Exception as e:
    logger.error(f"CRITICAL ERROR: Error initializing Google Cloud Storage client: {e}")
    sys.exit(f"Failed to initialize GCS client: {e}")

# --- API Routes ---

@app.route('/')
def serve_index():
    """Serves the index.html file from the frontend folder."""
    logger.info(f"Attempting to serve index.html from: {FRONTEND_FOLDER}")
    if not os.path.isfile(os.path.join(FRONTEND_FOLDER, 'index.html')):
        logger.error(f"index.html not found in {FRONTEND_FOLDER}")
        return "Error: Frontend index file not found.", 404
    try:
        return send_from_directory(FRONTEND_FOLDER, 'index.html')
    except Exception as e:
        logger.error(f"Error serving index.html: {e}")
        return "Error loading page. Check server logs.", 500

@app.route('/api/upload', methods=['POST'])
def upload_file():
    """Handles image uploads to GCS (privately)."""
    if 'image' not in request.files:
        logger.warning("Upload attempt failed: No 'image' file part in request.")
        return jsonify({"error": "No image file part in the request"}), 400

    file = request.files['image']

    if file.filename == '':
        logger.warning("Upload attempt failed: No file selected.")
        return jsonify({"error": "No selected file"}), 400

    if file:
        try:
            blob_name = file.filename
            blob = bucket.blob(blob_name)
            logger.info(f"Attempting to upload {blob_name} to bucket {BUCKET_NAME}.")
            blob.upload_from_file(file.stream, content_type=file.content_type)
            logger.info(f"File {blob_name} uploaded successfully to {BUCKET_NAME} (privately).")
            return jsonify({
                "message": f"File '{blob_name}' uploaded successfully (privately).",
                "filename": blob_name,
                "url": None
            }), 201
        except Exception as e:
            logger.error(f"Error uploading file '{file.filename}' to GCS: {e}")
            return jsonify({"error": f"Failed to upload file: {e}"}), 500
    else:
        logger.error("Unexpected state in upload_file: 'file' object exists but is falsey.")
        return jsonify({"error": "An unexpected error occurred during file processing"}), 500

@app.route('/api/images', methods=['GET'])
def get_image_urls():
    """Retrieves Signed URLs for accessing images using google-cloud-storage library."""
    urls = []
    try:
        logger.info(f"Listing blobs in bucket {BUCKET_NAME} for /api/images")
        blobs = bucket.list_blobs()
        for blob in blobs:
            try:
                logger.info(f"Credential type before signing: {type(storage_client._credentials)}")
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=15),
                    method="GET"
                )
                urls.append(signed_url)
            except Exception as e_sign:
                logger.error(f"Could not generate signed URL for {blob.name}: {e_sign}")
        logger.info(f"Generated {len(urls)} signed URLs out of {len(list(bucket.list_blobs()))} blobs found.")
        return jsonify(urls), 200
    except Exception as e:
        logger.error(f"Error listing blobs or generating URLs in /api/images: {e}")
        return jsonify({"error": f"Failed to retrieve image URLs: {e}"}), 500

@app.route('/api/list-images', methods=['GET'])
def list_image_metadata():
    """Retrieves metadata including a Signed URL using google-cloud-storage library."""
    image_info_list = []
    try:
        logger.info(f"Listing blobs in bucket {BUCKET_NAME} for /api/list-images")
        blobs = bucket.list_blobs()
        for blob in blobs:
            signed_url = None
            try:
                logger.info(f"Credential type before signing (metadata): {type(storage_client._credentials)}")
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=15),
                    method="GET"
                )
            except Exception as e_sign:
                logger.error(f"Could not generate signed URL for {blob.name} in metadata list: {e_sign}")

            image_info_list.append({
                "name": blob.name,
                "filename": blob.name,
                "url": signed_url,
                "size": blob.size,
                "updated": blob.updated.isoformat() if blob.updated else None
            })
        logger.info(f"Generated metadata for {len(image_info_list)} blobs out of {len(list(bucket.list_blobs()))} found.")
        return jsonify(image_info_list), 200
    except Exception as e:
        logger.error(f"Error listing blob metadata in /api/list-images: {e}")
        return jsonify({"error": f"Failed to retrieve image list: {e}"}), 500

@app.route('/api/delete-image/<path:filename>', methods=['DELETE'])
def delete_image(filename):
    """Deletes an image from the GCS bucket. Handles potential path characters."""
    if not filename:
        logger.warning("Delete attempt failed: Empty filename provided.")
        return jsonify({"error": "Filename cannot be empty."}), 400

    try:
        logger.info(f"Attempting to delete blob '{filename}' from bucket {BUCKET_NAME}.")
        blob = bucket.blob(filename)
        if not blob.exists():
            logger.warning(f"Delete failed: File '{filename}' not found in bucket {BUCKET_NAME}.")
            return jsonify({"error": f"File '{filename}' not found."}), 404
        blob.delete()
        logger.info(f"File '{filename}' deleted successfully from {BUCKET_NAME}")
        return jsonify({"message": f"File '{filename}' deleted successfully."}), 200
    except Exception as e:
        logger.error(f"Error deleting file '{filename}' from GCS: {e}")
        return jsonify({"error": f"Failed to delete file '{filename}'."}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))