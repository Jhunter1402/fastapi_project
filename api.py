import logging 
import random
import string
import pymongo
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import cv2
from ultralytics import YOLO
import uvicorn
import os
from dotenv import load_dotenv

load_dotenv()

# Initialize the FastAPI app
app = FastAPI()

# MongoDB Client setup using environment variables
mongo_uri = os.getenv("MONGO_URI")  # Get the Mongo URI from the environment
client = pymongo.MongoClient(mongo_uri)  # Use the URI from the .env file
db = client[os.getenv("MONGO_DB_NAME")]
detection_collection = db[os.getenv("MONGO_COLLECTION_ANALYTICS")]
status_collection = db[os.getenv("MONGO_COLLECTION_STATUS")]
log_collection = db[os.getenv("MONGO_COLLECTION_LOGS")]

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Pydantic model for request/response data validation
class DetectionRequest(BaseModel):
    sourceId: str
    video_url: str
    detection_type: str  # This will determine which model to load

# Pydantic model for token-based responses
class TokenModel(BaseModel):
    token: str

# Function to generate a random alphanumeric token
def generate_token():
    while True:
        token = ''.join(random.choices(string.ascii_letters + string.digits, k=6))
        if status_collection.find_one({"token": token}) is None:
            return token

# Function to log messages to MongoDB
def log_to_db(token, message):
    log_collection.insert_one({
        "token": token,
        "message": message,
        "timestamp": datetime.now()
    })

# Function to process video and run detection
def process_video(video_url: str, detection_type: str, sourceId: str, token: str):
    log_to_db(token, f"Started processing video from {video_url} with detection type {detection_type}")
    try:
        # Load the appropriate model based on detection type
        weights = os.path.join("weights", detection_type, "best_weight.pt")
        model = YOLO(weights)
        log_to_db(token, f"Loaded model with weights {weights}")
        
        # Open the video stream (could be URL or file)
        video_capture = cv2.VideoCapture(video_url)
        if not video_capture.isOpened():
            log_to_db(token, "Failed to open video source")
            status_collection.update_one({"token": token}, {"$set": {"status": "Failed", "timestamp": datetime.now()}})
            return

        frame_number = 0

        while True:
            ret, frame = video_capture.read()
            if not ret:
                log_to_db(token, "No more frames to read or failed to read frame.")
                status_collection.update_one({"token": token}, {"$set": {"status": "Failed", "timestamp": datetime.now()}})
                break  # No more frames to process

            frame_number += 1
            start_time = datetime.now()
            # Perform YOLO detection on the current frame
            try:
                detection_output = model.predict(source=frame, conf=0.25, save=False)
                class_names=detection_output[0].names
                a = detection_output[0].boxes
                classes = a.cls.cpu().numpy()
                detected_objects = []
                for i in range(len(classes)):
                    names = class_names[int(classes[i])]
                    detected_objects.append(names)

                log_to_db(token, f"Frame {frame_number}: Detected objects: {detected_objects}")
                # Save the detection results into MongoDB
                end_time = datetime.now()
                detection_collection.insert_one({
                    "sourceId": sourceId,
                    "frameNumber": frame_number,
                    "startTime": start_time,
                    "endTime": end_time,
                    "detectedObjects": detected_objects
                })
            except Exception as e:
                log_to_db(token, f"Error during model prediction: {e}")
                status_collection.update_one({"token": token}, {"$set": {"status": "Failed", "timestamp": datetime.now()}})
                break
        log_to_db(token, "Video processing completed.")
        video_capture.release()
        status_collection.update_one({"token": token}, {"$set": {"status": "Completed", "timestamp": datetime.now()}})
        log_to_db(token, "Video processing completed.")

    except Exception as e:
        log_to_db(token, f"Error during processing: {str(e)}")
        status_collection.update_one({"token": token}, {"$set": {"status": "Failed", "timestamp": datetime.now()}})

# Root endpoint
@app.get("/")
def read_root():
    return {"message": "Welcome to FastAPI!"}

@app.post("/detection")
def get_detections(request: DetectionRequest, background_tasks: BackgroundTasks):
    try:
        token = generate_token()
        status_collection.insert_one({
            "token": token,
            "status": "inProgress",
            "timestamp": datetime.now()
        })
        # Process the video and get detections based on detection type
        background_tasks.add_task(process_video, request.video_url, request.detection_type, request.sourceId, token)
        return {"Results": token}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/status")
def get_detection_status(token_model: TokenModel):
    token = token_model.token
    last_status = status_collection.find_one({"token": token})

    if not last_status:
        raise HTTPException(status_code=404, detail="Detection job not found")

    if last_status["status"] == "inProgress":
        status_collection.update_one(
            {"token": token, "status": "inProgress"},
            {"$set": {"timestamp": datetime.now()}}
        )
    status = status_collection.find_one({"token": token})
    return {
        "status": status["status"],
        "startTime": status["timestamp"]
    }

# Run the FastAPI app with reload (for development purposes)
if __name__ == "__main__":
    uvicorn.run("api:app", host="0.0.0.0", port=8000)
