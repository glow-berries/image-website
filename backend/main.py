import os
import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from google.cloud import storage
from dotenv import load_dotenv
import logging
import sys

FRONTEND_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))

# --- Configuration ---
load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    stream=sys.stderr
)
logger = logging.getLogger(__name__)
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")

if not BUCKET_NAME:
    logger.error("Error: GCS_BUCKET_NAME not set in .env")
    exit(1)

# --- Initialize Flask App and GCS Client ---
app = Flask(__name__, static_folder=FRONTEND_FOLDER, static_url_path='')
CORS(app)

try:
    storage_client = storage.Client()  # Authenticates using the Cloud Run service identity
    bucket = storage_client.bucket(BUCKET_NAME)
    logger.info(f"Successfully connected to GCS bucket: {BUCKET_NAME}")
except Exception as e:
    logger.error(f"Error initializing Google Cloud Storage client: {e}")
    exit(1)

# --- API Routes ---

@app.route('/')
def serve_index():
    """Serves the index.html file from the frontend folder."""
    logger.info(f"Attempting to serve index.html from: {FRONTEND_FOLDER}")
    try:
        return send_from_directory(FRONTEND_FOLDER, 'index.html')
    except Exception as e:
        logger.error(f"Error serving index.html: {e}")
        return "Error loading page. Check logs.", 500

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
            blob_name = file.filename
            blob = bucket.blob(blob_name)
            blob.upload_from_file(file.stream, content_type=file.content_type)
            logger.info(f"File {blob_name} uploaded successfully to {BUCKET_NAME} (privately).")
            return jsonify({
                "message": f"File '{blob_name}' uploaded successfully (privately).",
                "filename": blob_name,
                "url": None
            }), 201
        except Exception as e:
            logger.error(f"Error uploading file to GCS: {e}")
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
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=15),
                    method="GET"
                )
                urls.append(signed_url)
            except Exception as e_sign:
                logger.error(f"Could not generate signed URL for {blob.name}: {e_sign}. Check IAM permissions.")
        return jsonify(urls), 200
    except Exception as e:
        logger.error(f"Error listing blobs or generating URLs: {e}")
        return jsonify({"error": f"Failed to retrieve image URLs: {e}"}), 500

@app.route('/api/list-images', methods=['GET'])
def list_image_metadata():
    """Retrieves metadata including a Signed URL for access."""
    image_info_list = []
    try:
        blobs = bucket.list_blobs()
        for blob in blobs:
            signed_url = None
            try:
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=15),
                    method="GET"
                )
            except Exception as e_sign:
                logger.error(f"Could not generate signed URL for {blob.name} in metadata list: {e_sign}. Check IAM permissions.")

            image_info_list.append({
                "name": blob.name,
                "filename": blob.name,
                "url": signed_url,
                "size": blob.size,
                "updated": blob.updated.isoformat() if blob.updated else None
            })
        return jsonify(image_info_list), 200
    except Exception as e:
        logger.error(f"Error listing blob metadata: {e}")
        return jsonify({"error": f"Failed to retrieve image list: {e}"}), 500

@app.route('/api/delete-image/<filename>', methods=['DELETE'])
def delete_image(filename):
    """Deletes an image from the GCS bucket."""
    try:
        blob = bucket.blob(filename)
        blob.delete()
        logger.info(f"File {filename} deleted successfully from {BUCKET_NAME}")
        return jsonify({"message": f"File '{filename}' deleted successfully."}), 200
    except Exception as e:
        logger.error(f"Error deleting file {filename} from GCS: {e}")
        return jsonify({"error": f"Failed to delete file '{filename}': {e}"}), 500

# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)