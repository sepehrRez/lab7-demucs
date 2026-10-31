import json
import os
import shutil

import redis
import requests
from minio import Minio

redisHost = os.getenv("REDIS_HOST") or "localhost"
redisPort = int(os.getenv("REDIS_PORT") or 6379)
minioHost = os.getenv("MINIO_HOST") or "localhost:9000"
minioUser = os.getenv("MINIO_USER") or "rootuser"
minioPasswd = os.getenv("MINIO_PASSWD") or "rootpass123"

redisClient = redis.StrictRedis(host=redisHost, port=redisPort, db=0)
minioClient = Minio(minioHost, secure=False,
                    access_key=minioUser, secret_key=minioPasswd)

tracks = ["bass", "drums", "other", "vocals"]


def log(message):
    print(message, flush=True)
    redisClient.lpush("logging", "worker: " + message)


def process(work):
    songhash = work["songhash"]
    model = work.get("model") or "mdx_extra_q"
    callback = work.get("callback")

    inpath = "/tmp/" + songhash + ".mp3"
    outdir = "/tmp/output"

    if not minioClient.bucket_exists("output"):
        minioClient.make_bucket("output")

    log("getting " + songhash + " from minio")
    minioClient.fget_object("queue", songhash + ".mp3", inpath)

    log("running demucs on " + songhash)
    result = os.system("python3 -m demucs.separate --mp3 -n " + model +
                       " --out " + outdir + " " + inpath)
    if result != 0:
        log("demucs failed on " + songhash + " (not enough memory?)")
        return

    for track in tracks:
        path = outdir + "/" + model + "/" + songhash + "/" + track + ".mp3"
        minioClient.fput_object("output", songhash + "-" + track + ".mp3", path)
    log("finished " + songhash)

    # clean up so the disk doesn't fill up
    shutil.rmtree(outdir, ignore_errors=True)
    os.remove(inpath)

    # the callback may fail and that is ok
    if callback:
        try:
            requests.post(callback["url"], json=callback.get("data"))
        except Exception as e:
            log("callback failed: " + str(e))


log("worker started")
while True:
    try:
        item = redisClient.blpop("toWorker", timeout=0)
        work = json.loads(item[1].decode("utf-8"))
        process(work)
    except Exception as e:
        log("exception in worker: " + str(e))
