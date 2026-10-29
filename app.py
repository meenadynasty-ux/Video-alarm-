import os
import glob
import uuid
import shutil
import threading
import traceback
from flask import Flask, request, jsonify
import yt_dlp
import cloudinary
import cloudinary.uploader

app = Flask(__name__)

# ⚡ एक समय में केवल एक ही वीडियो प्रोसेस होगा (Zero Server Crash Lock)
VIDEO_PROCESS_LOCK = threading.Lock()

# 🗑️ टेम्परेरी फाइलों के लिए सुरक्षित फोल्डर
TEMP_DIR = os.path.join(os.getcwd(), "temp_alarm_media")
os.makedirs(TEMP_DIR, exist_ok=True)

# 🔐 Cloudinary कॉन्फ़िगरेशन (wklus6lr)
if os.environ.get("CLOUDINARY_URL"):
    cloudinary.config(secure=True)
else:
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME", "wklus6lr"),
        api_key=os.environ.get("CLOUDINARY_API_KEY", "313669668948322"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET", "8vVm4ptp4-Cf-uHMkn6fehtcrrA"),
        secure=True
    )


def cleanup_temp_files(job_prefix=None):
    """काम पूरा होते ही बैकएंड में बनी टेम्परेरी वीडियो फाइल को तुरंत डिलीट करने का फंक्शन"""
    try:
        if job_prefix:
            pattern = os.path.join(TEMP_DIR, f"{job_prefix}*")
            for fpath in glob.glob(pattern):
                try:
                    if os.path.isfile(fpath):
                        os.remove(fpath)
                    elif os.path.isdir(fpath):
                        shutil.rmtree(fpath, ignore_errors=True)
                except Exception:
                    pass
        else:
            for item in os.listdir(TEMP_DIR):
                item_path = os.path.join(TEMP_DIR, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                except Exception:
                    pass
    except Exception:
        pass


def upload_local_file_to_cloudinary(local_path):
    """लोकल टेम्परेरी फाइल को Cloudinary (wklus6lr) पर अपलोड करके डायरेक्ट .mp4 लिंक लौटाएगा"""
    upload_result = cloudinary.uploader.upload_large(
        local_path,
        resource_type="video",
        public_id="vvip_alarm_active_stream",
        folder="meena_video_alarm",
        overwrite=True,
        invalidate=True,
        format="mp4"
    )
    secure_mp4_url = upload_result.get("secure_url", "")
    if secure_mp4_url and not secure_mp4_url.endswith(".mp4"):
        base_part = secure_mp4_url.rsplit(".", 1)[0]
        secure_mp4_url = f"{base_part}.mp4"
    return secure_mp4_url, upload_result


@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "online",
        "service": "Meena VVIP Video Alarm Backend Resolver v2",
        "cloud_name": "wklus6lr",
        "queue_locked": VIDEO_PROCESS_LOCK.locked()
    }), 200


@app.route("/resolve", methods=["POST"])
def resolve_and_upload_to_cloudinary():
    """
    किसी भी प्लेटफॉर्म (YouTube, Instagram, Facebook, Moj, Snapchat, TikTok, X, Vimeo)
    के URL को प्रोसेस करके सीधा Cloudinary MP4 URL देगा।
    """
    try:
        data = request.get_json(silent=True) or {}
        raw_url = (data.get("url") or request.form.get("url") or "").strip()

        if not raw_url:
            return jsonify({"status": "error", "message": "कृपया कोई वैध वीडियो URL भेजें"}), 400

        if "res.cloudinary.com/" in raw_url and raw_url.endswith(".mp4"):
            return jsonify({
                "status": "success",
                "cloudinary_url": raw_url
            }), 200

        with VIDEO_PROCESS_LOCK:
            job_id = f"job_{uuid.uuid4().hex[:10]}"
            output_template = os.path.join(TEMP_DIR, f"{job_id}.%(ext)s")

            try:
                # अलग-अलग प्रोफाइल्स ताकि अगर एक क्लाइंट ब्लॉक हो तो दूसरा तुरंत काम करे
                client_profiles = [
                    {"youtube": {"player_client": ["android_vr", "tv", "ios"]}},
                    {"youtube": {"player_client": ["ios", "mweb", "web_embedded"]}},
                    {}
                ]

                extracted_ok = False
                last_err = ""

                for profile in client_profiles:
                    cleanup_temp_files(job_id)
                    ydl_opts = {
                        "format": "best[ext=mp4]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best",
                        "merge_output_format": "mp4",
                        "outtmpl": output_template,
                        "noplaylist": True,
                        "quiet": True,
                        "no_warnings": True,
                        "geo_bypass": True,
                        "nocheckcertificate": True,
                        "max_filesize": 65 * 1024 * 1024,
                        "socket_timeout": 25,
                        "retries": 3,
                    }
                    if profile:
                        ydl_opts["extractor_args"] = profile

                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.extract_info(raw_url, download=True)

                        matched = glob.glob(os.path.join(TEMP_DIR, f"{job_id}*"))
                        if matched and os.path.exists(matched[0]) and os.path.getsize(matched[0]) > 1024:
                            extracted_ok = True
                            break
                    except Exception as ex:
                        last_err = str(ex)

                matched_files = glob.glob(os.path.join(TEMP_DIR, f"{job_id}*"))
                if not extracted_ok or not matched_files:
                    return jsonify({
                        "status": "error",
                        "message": f"Extractor failed: {last_err}"
                    }), 422

                downloaded_file_path = matched_files[0]
                secure_mp4_url, upload_result = upload_local_file_to_cloudinary(downloaded_file_path)

                if not secure_mp4_url:
                    return jsonify({
                        "status": "error",
                        "message": "Cloudinary से URL प्राप्त नहीं हुआ"
                    }), 500

                return jsonify({
                    "status": "success",
                    "cloudinary_url": secure_mp4_url,
                    "public_id": upload_result.get("public_id", ""),
                    "bytes": upload_result.get("bytes", 0)
                }), 200

            finally:
                # 🗑️ काम पूरा होते ही टेम्परेरी फाइल तुरंत डिलीट करें
                cleanup_temp_files(job_id)

    except Exception as e:
        traceback.print_exc()
        cleanup_temp_files()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


@app.route("/upload_cloudinary", methods=["POST"])
def upload_binary_or_stream_to_cloudinary():
    """
    यदि ऐप ने फोन के 5G नेटवर्क से वीडियो स्ट्रीम निकाला है या गैलरी फाइल भेजी है,
    तो उसे सीधे Cloudinary (wklus6lr) में अपलोड करके MP4 URL लौटाएगा और टेम्परेरी फाइल डिलीट कर देगा।
    """
    with VIDEO_PROCESS_LOCK:
        job_id = f"up_{uuid.uuid4().hex[:10]}"
        temp_path = os.path.join(TEMP_DIR, f"{job_id}.mp4")
        try:
            if "file" in request.files:
                f = request.files["file"]
                f.save(temp_path)
            else:
                with open(temp_path, "wb") as out_f:
                    out_f.write(request.get_data())

            if not os.path.exists(temp_path) or os.path.getsize(temp_path) < 1024:
                return jsonify({"status": "error", "message": "Empty video data"}), 400

            secure_mp4_url, upload_result = upload_local_file_to_cloudinary(temp_path)
            return jsonify({
                "status": "success",
                "cloudinary_url": secure_mp4_url,
                "bytes": upload_result.get("bytes", 0)
            }), 200
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500
        finally:
            cleanup_temp_files(job_id)


if __name__ == "__main__":
    cleanup_temp_files()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
