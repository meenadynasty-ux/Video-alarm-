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

# ⚡ नियम: एक समय में केवल एक ही वीडियो प्रोसेस होगा (Zero Server Crash Lock)
VIDEO_PROCESS_LOCK = threading.Lock()

# 🗑️ टेम्परेरी फाइलों के लिए सुरक्षित फोल्डर
TEMP_DIR = os.path.join(os.getcwd(), "temp_alarm_media")
os.makedirs(TEMP_DIR, exist_ok=True)

# 🔐 Cloudinary कॉन्फ़िगरेशन (API Secret केवल बैकएंड Environment में सुरक्षित रहेगा)
# यदि आपने CLOUDINARY_URL=cloudinary://313669668948322:YOUR_SECRET@wklus6lr सेट किया है,
# तो यह अपने-आप उसे पढ़ लेगा, अन्यथा अलग-अलग वेरिएबल्स से लोड करेगा।
if os.environ.get("CLOUDINARY_URL"):
    cloudinary.config(secure=True)
else:
    cloudinary.config(
        cloud_name=os.environ.get("CLOUDINARY_CLOUD_NAME", "wklus6lr"),
        api_key=os.environ.get("CLOUDINARY_API_KEY", "313669668948322"),
        api_secret=os.environ.get("CLOUDINARY_API_SECRET", "YOUR_API_SECRET_HERE"),
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


@app.route("/", methods=["GET"])
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({
        "status": "online",
        "service": "Meena VVIP Video Alarm Backend Resolver",
        "cloud_name": "wklus6lr",
        "queue_locked": VIDEO_PROCESS_LOCK.locked()
    }), 200


@app.route("/resolve", methods=["POST"])
def resolve_and_upload_to_cloudinary():
    """
    Flow:
    User URL (YouTube / Instagram / FB / Moj / Snapchat / TikTok / X / Vimeo)
    -> yt-dlp Resolve (Temp File)
    -> Upload to Cloudinary (wklus6lr)
    -> Delete Temp File Immediately
    -> Return Direct Cloudinary MP4 URL to Video Alarm App
    """
    try:
        data = request.get_json(silent=True) or {}
        raw_url = (data.get("url") or request.form.get("url") or "").strip()

        if not raw_url:
            return jsonify({"status": "error", "message": "कृपया कोई वैध वीडियो URL भेजें"}), 400

        # अगर लिंक पहले से ही Cloudinary का डायरेक्ट वीडियो लिंक है, तो सीधे वापस भेजें
        if "res.cloudinary.com/" in raw_url and raw_url.endswith(".mp4"):
            return jsonify({
                "status": "success",
                "cloudinary_url": raw_url
            }), 200

        # ⚡ एक समय में एक ही वीडियो प्रोसेस करने के लिए लॉक लें
        with VIDEO_PROCESS_LOCK:
            job_id = f"job_{uuid.uuid4().hex[:10]}"
            output_template = os.path.join(TEMP_DIR, f"{job_id}.%(ext)s")
            downloaded_file_path = None

            try:
                # 1. किसी भी प्लेटफॉर्म से Android-Compatible MP4 वीडियो डाउनलोड करने की सेटिंग्स
                ydl_opts = {
                    "format": "best[ext=mp4][vcodec^=avc1]/best[ext=mp4]/best",
                    "outtmpl": output_template,
                    "noplaylist": True,
                    "quiet": True,
                    "no_warnings": True,
                    "geo_bypass": True,
                    "max_filesize": 60 * 1024 * 1024,  # 60 MB Max ताकि तेज़ी से प्रोसेस हो
                    "socket_timeout": 25,
                    "retries": 3,
                    "http_headers": {
                        "User-Agent": (
                            "Mozilla/5.0 (Linux; Android 14; Mobile) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/124.0.0.0 Mobile Safari/537.36"
                        )
                    }
                }

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.extract_info(raw_url, download=True)

                # डाउनलोड हुई टेम्परेरी फाइल ढूँढें
                matched_files = glob.glob(os.path.join(TEMP_DIR, f"{job_id}*"))
                if not matched_files:
                    return jsonify({
                        "status": "error",
                        "message": "इस लिंक से वीडियो एक्सट्रैक्ट नहीं हो सका"
                    }), 422

                downloaded_file_path = matched_files[0]

                if not os.path.exists(downloaded_file_path) or os.path.getsize(downloaded_file_path) < 1024:
                    return jsonify({
                        "status": "error",
                        "message": "डाउनलोड की गई वीडियो फाइल खाली या अमान्य है"
                    }), 422

                # 2. वीडियो को सीधे Cloudinary (wklus6lr) में अपलोड करें
                # overwrite=True रखने से हर नए URL पर यही स्लॉट अपडेट होगा और Cloudinary स्टोरेज कभी फुल नहीं होगा!
                upload_result = cloudinary.uploader.upload_large(
                    downloaded_file_path,
                    resource_type="video",
                    public_id="vvip_alarm_active_stream",
                    folder="meena_video_alarm",
                    overwrite=True,
                    invalidate=True,
                    format="mp4"
                )

                secure_mp4_url = upload_result.get("secure_url", "")
                if not secure_mp4_url:
                    return jsonify({
                        "status": "error",
                        "message": "Cloudinary से URL प्राप्त नहीं हुआ"
                    }), 500

                # सुनिश्चित करें कि URL .mp4 एक्सटेंशन के साथ हो ताकि Android VideoView 0.0ms में चले
                if not secure_mp4_url.endswith(".mp4"):
                    base_part = secure_mp4_url.rsplit(".", 1)[0]
                    secure_mp4_url = f"{base_part}.mp4"

                return jsonify({
                    "status": "success",
                    "cloudinary_url": secure_mp4_url,
                    "public_id": upload_result.get("public_id", ""),
                    "bytes": upload_result.get("bytes", 0)
                }), 200

            finally:
                # 🗑️ 3. काम पूरा होते ही (या एरर आने पर भी) बैकएंड से टेम्परेरी फाइल तुरंत डिलीट करें!
                cleanup_temp_files(job_id)

    except Exception as e:
        traceback.print_exc()
        cleanup_temp_files()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


if __name__ == "__main__":
    # सर्वर स्टार्ट होते समय पुरानी कोई भी बची हुई टेम्परेरी फाइल साफ कर दें
    cleanup_temp_files()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
