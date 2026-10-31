import base64
import hashlib
import io
import json
import os

import redis
from flask import Flask, Response, jsonify, request
from minio import Minio
from minio.error import S3Error

redisHost = os.getenv("REDIS_HOST") or "localhost"
redisPort = int(os.getenv("REDIS_PORT") or 6379)
minioHost = os.getenv("MINIO_HOST") or "localhost:9000"
minioUser = os.getenv("MINIO_USER") or "rootuser"
minioPasswd = os.getenv("MINIO_PASSWD") or "rootpass123"

app = Flask(__name__)

redisClient = redis.StrictRedis(host=redisHost, port=redisPort, db=0)
minioClient = Minio(minioHost, secure=False,
                    access_key=minioUser, secret_key=minioPasswd)

tracks = ["bass", "drums", "other", "vocals"]


def log(message):
    print(message, flush=True)
    redisClient.lpush("logging", "rest: " + message)


def make_buckets():
    for name in ["queue", "output"]:
        if not minioClient.bucket_exists(name):
            minioClient.make_bucket(name)


def track_name(track):
    # accepts "bass", "bass.mp3" and also "base.mp3" like the README says
    track = track.replace(".mp3", "")
    if track == "base":
        track = "bass"
    if track in tracks:
        return track
    return None


@app.route("/", methods=["GET"])
def hello():
    return "<h1> Music Separation Server</h1><p> Use a valid endpoint </p>"


@app.route("/apiv1/separate", methods=["POST"])
def separate():
    try:
        body = json.loads(request.data.decode("utf-8"))
        mp3 = base64.b64decode(body["mp3"])
    except Exception as e:
        return jsonify({"reason": "bad request: " + str(e)}), 400

    songhash = hashlib.sha224(mp3).hexdigest()

    make_buckets()
    minioClient.put_object("queue", songhash + ".mp3", io.BytesIO(mp3), len(mp3))

    work = {
        "songhash": songhash,
        "model": body.get("model", "mdx_extra_q"),
        "callback": body.get("callback"),
    }
    redisClient.lpush("toWorker", json.dumps(work))

    log("enqueued " + songhash)
    return jsonify({"hash": songhash, "reason": "Song enqueued for separation"})


@app.route("/apiv1/queue", methods=["GET"])
def queue():
    entries = []
    for item in redisClient.lrange("toWorker", 0, -1):
        entries.append(json.loads(item.decode("utf-8"))["songhash"])
    return jsonify({"queue": entries})


@app.route("/apiv1/track/<songhash>/<track>", methods=["GET"])
def get_track(songhash, track):
    name = track_name(track)
    if name is None:
        return jsonify({"reason": "unknown track " + track}), 400

    obj = songhash + "-" + name + ".mp3"
    try:
        response = minioClient.get_object("output", obj)
        data = response.read()
        response.close()
        response.release_conn()
    except S3Error:
        return jsonify({"reason": obj + " not found"}), 404

    return Response(data, mimetype="audio/mpeg")


@app.route("/apiv1/remove/<songhash>/<track>", methods=["GET", "DELETE"])
def remove_track(songhash, track):
    name = track_name(track)
    if name is None:
        return jsonify({"reason": "unknown track " + track}), 400

    obj = songhash + "-" + name + ".mp3"
    try:
        minioClient.stat_object("output", obj)
        minioClient.remove_object("output", obj)
    except S3Error:
        return jsonify({"reason": obj + " not found"}), 404

    log("removed " + obj)
    return jsonify({"reason": "removed " + obj})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
