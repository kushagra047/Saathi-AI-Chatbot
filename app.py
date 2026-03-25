from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from groq import Groq
import os
from datetime import datetime
from dotenv import load_dotenv
from flask_migrate import Migrate  # ADDED: Professional Database Versioning

# Load environment variables
load_dotenv()

app = Flask(__name__)

# Configs
app.config['SECRET_KEY'] = os.getenv('FLASK_SECRET_KEY', 'default_secret_key_just_in_case') 

# UPDATED: Cloud MySQL support with local SQLite fallback
uri = os.getenv("DATABASE_URL", "sqlite:///saathi.db")
if uri and uri.startswith("postgres://"):
    uri = uri.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = uri
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SESSION_COOKIE_HTTPONLY'] = True  
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax' 

# Database & Migration Setup
db = SQLAlchemy(app)
migrate = Migrate(app, db)  # ADDED: Links Flask-Migrate to your DB

# Login Manager Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login' 

# AI Client Setup
client = Groq(api_key=os.getenv('GROQ_API_KEY'))
bot_name = "Saathi"

# --- ADVANCED SYSTEM PROMPT ---
system_prompt = f"""
You are '{bot_name}', a cool, modern Indian therapist and a deeply empathetic best friend. 
Your goal is to help the user feel heard first, and then give them a small mental health exercise.

=== CORE LANGUAGE RULES ===
1. USER WRITES IN ENGLISH -> Reply in 100% Chill English.
2. USER WRITES IN HINGLISH -> Reply in casual, supportive Hinglish (Roman script only).
3. NO SHUDDH HINDI: Never use words like 'bhavnaon', 'sahayata', 'kathin', 'asamanjas', 'udasi'. Use 'Feelings', 'Help', 'Mushkil', 'Confused', 'Sad' instead.
4. TONE: Friendly (Yaar/Dost vibe). No medical lectures.

=== CONVERSATION FLOW (THE RULE OF 3) ===
- MESSAGE 1 & 2: ONLY EMPATHY. Listen to the user, validate their feelings. Do NOT give any exercise yet.
- MESSAGE 3 ONWARDS: Identify the user's core issue and suggest ONE specific exercise from the Toolbox below.
- STRICT RULE: Do not jump to exercises immediately. Pehle dosti, phir therapy.

=== THERAPEUTIC TOOLBOX (Pick 1 based on issue) ===
- ANXIETY/PANIC: Suggest '5-4-3-2-1 Grounding' (5 things you see, 4 you feel...).
- NEGATIVE THOUGHTS: Suggest 'Thought Challenging' (Pucho: Kya ye fact hai ya sirf ek feeling?).
- DEPRESSION/LOW ENERGY: Suggest 'Behavioral Activation' (Ek chota 2-minute task karne ko bolo).
- STRESS/OVERWHELM: Suggest 'Brain Dump' (Sab kuch paper par likhne ko bolo).

=== EMERGENCY PROTOCOL ===
- If the user mentions self-harm or suicide, IGNORE THE 3-MESSAGE RULE and provide:
- Vandrevala Foundation: +91 9999666555 | KIRAN: 1800-599-0019.

STRICT NEGATIVE CONSTRAINT: Never repeat the same exercise twice. Keep it natural and conversational.
"""

# --- DATABASE MODELS (NO CHANGES HERE) ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(256), nullable=False) 
    chats = db.relationship('ChatSession', backref='user', lazy=True)

class ChatSession(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), default="New Chat")
    is_pinned = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    messages = db.relationship('Message', backref='chat', lazy=True, cascade="all, delete-orphan")

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    role = db.Column(db.String(50), nullable=False) 
    chat_id = db.Column(db.Integer, db.ForeignKey('chat_session.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- ROUTES (LOGIN/REGISTER - NO CHANGES) ---
@app.route('/')
def home():
    if current_user.is_authenticated: return redirect(url_for('chat_home'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if User.query.filter_by(username=username).first():
            flash('Username taken.')
            return redirect(url_for('register'))
        new_user = User(username=username, password=generate_password_hash(password))
        db.session.add(new_user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            login_user(user)
            return redirect(url_for('chat_home'))
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/chat')
@login_required
def chat_home():
    all_chats = ChatSession.query.filter_by(user_id=current_user.id).order_by(ChatSession.is_pinned.desc(), ChatSession.created_at.desc()).all()
    if not all_chats:
        new_s = ChatSession(user_id=current_user.id)
        db.session.add(new_s)
        db.session.commit()
        return redirect(url_for('load_chat', chat_id=new_s.id))
    return redirect(url_for('load_chat', chat_id=all_chats[0].id))

@app.route('/chat/<int:chat_id>')
@login_required
def load_chat(chat_id):
    current_chat = ChatSession.query.get_or_404(chat_id)
    all_chats = ChatSession.query.filter_by(user_id=current_user.id).order_by(ChatSession.is_pinned.desc(), ChatSession.created_at.desc()).all()
    messages = Message.query.filter_by(chat_id=chat_id).all()
    return render_template('chat.html', chats=all_chats, current_chat=current_chat, messages=messages, username=current_user.username)

# --- UPDATED: GET_RESPONSE WITH INTEGRATED SAFETY ---
@app.route('/get_response', methods=['POST'])
@login_required
def get_response():
    data = request.json
    user_msg = data.get("message", "")
    chat_id = data.get("chat_id")
    
    if not user_msg or not chat_id:
        return jsonify({"reply": "System Error: Missing Message or Chat ID"}), 400

    # 1. SAFETY BYPASS CHECK
    emergency_keywords = ["end my life", "suicide", "marne ka mann", "kill myself", "zeher", "ending it all"]
    if any(word in user_msg.lower() for word in emergency_keywords):
        user_name = current_user.username if current_user.is_authenticated else "there"
        emergency_reply = (
            f"Please listen to me, {user_name}. You are not alone, and there is help available for what you're going through. "
            "Your life is incredibly valuable, far more than any temporary struggle. "
            "Please reach out to these support services right now:\n\n"
            "1. Vandrevala Foundation (India): +91 9999666555\n"
            "2. KIRAN Helpline (India): 1800-599-0019\n"
            "3. Global Support: https://findahelpline.com\n\n"
            "Is there someone you trust that you can call right now? Please stay with me."
        )
        db.session.add(Message(content=user_msg, role='user', chat_id=chat_id))
        db.session.add(Message(content=emergency_reply, role='assistant', chat_id=chat_id))
        db.session.commit()
        return jsonify({"reply": emergency_reply})

    # 2. NORMAL FLOW
    db.session.add(Message(content=user_msg, role='user', chat_id=chat_id))
    chat_s = ChatSession.query.get(chat_id)
    if chat_s.title == "New Chat": 
        chat_s.title = user_msg[:20] + "..."
    db.session.commit()

    chat_history = [{"role": "system", "content": system_prompt}]
    past_messages = Message.query.filter_by(chat_id=chat_id).order_by(Message.id).all()[-15:]
    for m in past_messages:
        chat_history.append({"role": m.role, "content": m.content})

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=chat_history,
            temperature=0.7
        )
        reply = completion.choices[0].message.content
        db.session.add(Message(content=reply, role='assistant', chat_id=chat_id))
        db.session.commit()
        return jsonify({"reply": reply})
    except Exception as e:
        return jsonify({"reply": "I'm having a bit of a technical glitch. Can you try again?"})

# --- UTILITY ROUTES (DELETE/PIN/SHARE - NO CHANGES) ---
@app.route('/new_chat')
@login_required
def new_chat():
    ns = ChatSession(user_id=current_user.id); db.session.add(ns); db.session.commit()
    return redirect(url_for('load_chat', chat_id=ns.id))

@app.route('/delete_chat/<int:chat_id>', methods=['POST'])
@login_required
def delete_chat(chat_id):
    chat = ChatSession.query.get_or_404(chat_id)
    if chat.user_id == current_user.id:
        db.session.delete(chat)
        db.session.commit()
    return jsonify({"success": True})

@app.route('/pin_chat/<int:chat_id>', methods=['POST'])
@login_required
def pin_chat(chat_id):
    chat = ChatSession.query.get_or_404(chat_id)
    if chat.user_id == current_user.id:
        chat.is_pinned = not chat.is_pinned
        db.session.commit()
    return jsonify({"success": True})

@app.route('/share_chat/<int:chat_id>', methods=['GET'])
@login_required
def share_chat(chat_id):
    chat = ChatSession.query.get_or_404(chat_id)
    if chat.user_id != current_user.id:
        return jsonify({"error": "Unauthorized"}), 403
    
    messages = Message.query.filter_by(chat_id=chat_id).order_by(Message.id).all()
    chat_text = f"--- Saathi Chat: {chat.title} ---\n\n"
    for msg in messages:
        role = "You" if msg.role == "user" else "Saathi"
        chat_text += f"{role}: {msg.content}\n\n"
    
    return jsonify({"share_text": chat_text})

if __name__ == '__main__':
    with app.app_context():
        # NOTE: Once using Flask-Migrate, industry standard is to run migrations 
        # instead of create_all, but we keep this for local safety.
        db.create_all()
    app.run(debug=os.getenv('FLASK_DEBUG', 'False') == 'True')