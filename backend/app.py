import os, cv2, numpy as np, uuid, re, threading, time
from PIL import Image, ImageDraw, ImageFont
from flask import Flask, request, send_file, send_from_directory, jsonify
from flask_cors import CORS
from pyngrok import ngrok
import whisper 

# التوكن بتاعك
NGROK_AUTH_TOKEN = "3EmWNWSZwaGHosXreAhgsDmLqtP_5Q6b7PDypDMTxGhV3yfuu"
ngrok.set_auth_token(NGROK_AUTH_TOKEN)

# مسارات جوجل درايف الجديدة
PROJECT_DIR = '/content/drive/MyDrive/AutoCaptionApp'
FRONTEND_FOLDER = f'{PROJECT_DIR}/frontend'
INPUT_FOLDER = f'{PROJECT_DIR}/backend/input_videos'
OUTPUT_FOLDER = f'{PROJECT_DIR}/backend/output_videos'
FONTS_FOLDER = f'{PROJECT_DIR}/backend/fonts'
MODEL_FOLDER = f'{PROJECT_DIR}/backend/models'

print("⏳ جاري تحميل الموديل (large-v3)... (أول مرة بس هتاخد وقت)")
whisper_model = whisper.load_model("large-v3", download_root=MODEL_FOLDER)
print("✅ تم تحميل الموديل بنجاح!")

def auto_cleanup_routine():
    while True:
        time.sleep(300)
        try:
            now = time.time()
            for folder in [INPUT_FOLDER, OUTPUT_FOLDER]:
                if not os.path.exists(folder): continue
                for filename in os.listdir(folder):
                    filepath = os.path.join(folder, filename)
                    if os.path.isfile(filepath) and (now - os.path.getmtime(filepath)) > 900:
                        os.remove(filepath)
        except: pass

def hex_to_rgb(hex_color):
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4)) if len(hex_color) == 6 else (255, 165, 0)

def process_video_karaoke(video_input_path, video_output_path, font_path, text_color_rgb, position, font_size):
    normalized_video = os.path.join(OUTPUT_FOLDER, f"norm_{uuid.uuid4().hex[:6]}.mp4")
    os.system(f"ffmpeg -i '{video_input_path}' -c:v libx264 -preset veryfast -c:a aac -y '{normalized_video}' -loglevel quiet")
    
    if os.path.exists(normalized_video) and os.path.getsize(normalized_video) > 0:
        original_input = video_input_path
        video_input_path = normalized_video
    else:
        original_input = None

    prompt = "هذا تسجيل صوتي باللهجة السودانية. حافظ على أي كلمات أو مصطلحات أجنبية باللغة الإنجليزية كما نُطقت (مثل: Realme, Harry Potter). لا تقم بتعريب الكلمات الإنجليزية."
    result = whisper_model.transcribe(video_input_path, word_timestamps=True, language="ar", initial_prompt=prompt, condition_on_previous_text=False)
    
    raw_words = []
    sync_delay = 0.15 
    for segment in result.get("segments", []):
        for word_info in segment.get("words", []):
            raw_words.append({'word': word_info['word'].strip(), 'start': word_info['start'] + sync_delay, 'end': word_info['end'] + sync_delay})

    if not raw_words:
        os.system(f"cp '{video_input_path}' '{video_output_path}'")
        if original_input: os.remove(normalized_video)
        return

    logical_chunks = []
    current_chunk = []
    chunk_start = None

    for i, word_info in enumerate(raw_words):
        word_text = word_info['word']
        w_start, w_end = word_info['start'], word_info['end']
        
        if not current_chunk: chunk_start = w_start
        current_chunk.append({'word': word_text, 'start': w_start, 'end': w_end})
        
        next_pause = raw_words[i+1]['start'] - w_end if i < len(raw_words) - 1 else 0
        is_end_of_sentence = any(p in word_text for p in ['.', '!', '؟', '،', ','])

        if next_pause > 0.4 or is_end_of_sentence or len(current_chunk) >= 5:
            logical_chunks.append({'words': current_chunk, 'start': chunk_start, 'end': w_end + (0.3 if next_pause > 0.3 else 0)})
            current_chunk = [] 

    if current_chunk:
        logical_chunks.append({'words': current_chunk, 'start': chunk_start, 'end': current_chunk[-1]['end'] + 0.5})

    try: font = ImageFont.truetype(font_path, font_size)
    except Exception: font = ImageFont.load_default()

    cap = cv2.VideoCapture(video_input_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width, height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    temp_video = os.path.join(OUTPUT_FOLDER, f"temp_{uuid.uuid4().hex[:6]}.mp4")
    out = cv2.VideoWriter(temp_video, cv2.VideoWriter_fourcc(*'mp4v'), fps, (width, height))

    frame_idx = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret: break
        current_time = frame_idx / fps
        active_chunk = next((chunk for chunk in logical_chunks if chunk['start'] <= current_time < chunk['end']), None)
        
        if active_chunk:
            visible_words = [w['word'] for w in active_chunk['words'] if w['start'] <= current_time] or [active_chunk['words'][0]['word']]
            if visible_words:
                active_text = " ".join(visible_words).strip()
                active_text = re.sub(r'[\u200e\u200f\u202a\u202b\u202c\u202d\u202e]', '', active_text)
                
                pil_img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                draw = ImageDraw.Draw(pil_img)
                
                max_text_width = width * 0.85
                words = active_text.split()
                lines = []
                current_line = []
                
                for w in words:
                    current_line.append(w)
                    test_line = " ".join(current_line)
                    try:
                        bbox = draw.textbbox((0, 0), test_line, font=font, direction='rtl', language='ar')
                        test_w = bbox[2] - bbox[0]
                    except:
                        test_w = font_size * len(test_line)
                        
                    if test_w > max_text_width and len(current_line) > 1:
                        current_line.pop()
                        lines.append(" ".join(current_line))
                        current_line = [w]
                        
                if current_line:
                    lines.append(" ".join(current_line))
                
                total_height = 0
                line_heights = []
                for line in lines:
                    try:
                        bbox = draw.textbbox((0, 0), line, font=font, direction='rtl', language='ar')
                        lh = bbox[3] - bbox[1]
                    except:
                        lh = font_size
                    line_heights.append(lh)
                    total_height += lh + 15
                
                if position == 'top': y = int(height * 0.15)
                elif position == 'bottom': y = int(height * 0.85) - total_height
                else: y = (height - total_height) / 2
                
                for i, line in enumerate(lines):
                    try:
                        bbox = draw.textbbox((0, 0), line, font=font, direction='rtl', language='ar')
                        lw = bbox[2] - bbox[0]
                        x = (width - lw) / 2
                        draw.text((x, y), line, font=font, fill=text_color_rgb, stroke_width=4, stroke_fill=(0,0,0), direction='rtl', language='ar')
                    except: pass
                    y += line_heights[i] + 15

                frame = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
        out.write(frame)
        frame_idx += 1
    cap.release(); out.release()
    
    os.system(f"ffmpeg -i '{temp_video}' -i '{video_input_path}' -c:v libx264 -c:a copy -map 0:v:0 -map 1:a:0? -y '{video_output_path}' -loglevel error")
    
    if os.path.exists(temp_video): os.remove(temp_video)
    if original_input and os.path.exists(normalized_video): os.remove(normalized_video)

app = Flask(__name__, static_folder=FRONTEND_FOLDER)
CORS(app)
tasks_status = {}

def background_task(task_id, input_path, output_path, font_path, text_color, position, font_size):
    try:
        process_video_karaoke(input_path, output_path, font_path, text_color, position, font_size)
        tasks_status[task_id] = {'status': 'done', 'filename': os.path.basename(output_path)}
    except Exception as e: tasks_status[task_id] = {'status': 'error', 'message': str(e)}

@app.route('/')
def serve_website(): return send_from_directory(FRONTEND_FOLDER, 'index.html')

@app.route('/process-video', methods=['POST'])
def process_video():
    file = request.files['video']
    font_color_hex = request.form.get('fontColor', '#ffa500')
    position_option = request.form.get('position', 'center')
    font_size = int(request.form.get('fontSize', 60))
    
    selected_font_path = os.path.join(FONTS_FOLDER, 'font.ttf')
    if not os.path.exists(selected_font_path):
        fallback_fonts = [f for f in os.listdir(FONTS_FOLDER) if f.endswith('.ttf')]
        if fallback_fonts: selected_font_path = os.path.join(FONTS_FOLDER, fallback_fonts[0])

    input_path = os.path.join(INPUT_FOLDER, file.filename)
    file.save(input_path)
    output_path = os.path.join(OUTPUT_FOLDER, f"captioned_{file.filename}")
    task_id = str(uuid.uuid4())
    tasks_status[task_id] = {'status': 'processing'}
    threading.Thread(target=background_task, args=(task_id, input_path, output_path, selected_font_path, hex_to_rgb(font_color_hex), position_option, font_size)).start()
    return jsonify({"task_id": task_id})

@app.route('/status/<task_id>')
def check_status(task_id): return jsonify(tasks_status.get(task_id, {"status": "not_found"}))

@app.route('/download/<filename>')
def download_file(filename): return send_file(os.path.join(OUTPUT_FOLDER, filename), mimetype='video/mp4', as_attachment=True)

if __name__ == '__main__':
    threading.Thread(target=auto_cleanup_routine, daemon=True).start()
    try: ngrok.kill()
    except: pass
    
    public_url = ngrok.connect(5000)
    print(f"\n✅ السيرفر جاهز في Colab! (مع درع الحماية ضد صيغ الفيديو غير المدعومة 🛡)")
    print(f"🌍 افتح الرابط: {public_url.public_url}\n")
    
    app.run(port=5000)
