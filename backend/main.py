import os
import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from google.cloud import storage
from dotenv import load_dotenv
import logging

FRONTEND_FOLDER = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'frontend'))

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
    """Serves the index.html file from the frontend folder."""
    logging.info(f"Attempting to serve index.html from: {FRONTEND_FOLDER}")
    try:
        return send_from_directory(FRONTEND_FOLDER, 'index.html')
    except Exception as e:
        logging.error(f"Error serving index.html: {e}")
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
            logging.info(f"File {blob_name} uploaded successfully to {BUCKET_NAME} (privately).")
            return jsonify({
                "message": f"File '{blob_name}' uploaded successfully (privately).",
                "filename": blob_name,
                "url": None
            }), 201
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
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=15),
                    method="GET"
                )
                urls.append(signed_url)
            except Exception as e_sign:
                logging.error(f"Could not generate signed URL for {blob.name}: {e_sign}. Check IAM permissions.")
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
            signed_url = None
            try:
                signed_url = blob.generate_signed_url(
                    version="v4",
                    expiration=datetime.timedelta(minutes=15),
                    method="GET"
                )
            except Exception as e_sign:
                logging.error(f"Could not generate signed URL for {blob.name} in metadata list: {e_sign}. Check IAM permissions.")

            image_info_list.append({
                "name": blob.name,
                "filename": blob.name,
                "url": signed_url,
                "size": blob.size,
                "updated": blob.updated.isoformat() if blob.updated else None
            })
        return jsonify(image_info_list), 200
    except Exception as e:
        logging.error(f"Error listing blob metadata: {e}")
        return jsonify({"error": f"Failed to retrieve image list: {e}"}), 500

@app.route('/api/delete-image/<filename>', methods=['DELETE'])
def delete_image(filename):
    """Deletes an image from the GCS bucket."""
    try:
        blob = bucket.blob(filename)
        blob.delete()
        logging.info(f"File {filename} deleted successfully from {BUCKET_NAME}")
        return jsonify({"message": f"File '{filename}' deleted successfully."}), 200
    except Exception as e:
        logging.error(f"Error deleting file {filename} from GCS: {e}")
        return jsonify({"error": f"Failed to delete file '{filename}': {e}"}), 500

# --- Run the App ---
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)