import json
import hashlib
import uuid
import os
import sqlite3
import random
import datetime
from flask import Flask, request, jsonify, session, render_template
from cryptography.fernet import Fernet

app = Flask(__name__)
app.secret_key = 'supersecretkeyforsession'

KEY_FILE = "secret.key"
if os.path.exists(KEY_FILE):
    with open(KEY_FILE, "rb") as f:
        key = f.read()
else:
    key = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(key)
cipher = Fernet(key)

BLOCKCHAIN_FILE = "blockchain.json"

def load_chain():
    if os.path.exists(BLOCKCHAIN_FILE):
        with open(BLOCKCHAIN_FILE) as f:
            return json.load(f)
    genesis = {
        "index": 0,
        "timestamp": str(datetime.datetime.now()),
        "data": "Genesis",
        "previous_hash": "0",
        "hash": hashlib.sha256(b"Genesis").hexdigest()
    }
    with open(BLOCKCHAIN_FILE, "w") as f:
        json.dump([genesis], f)
    return [genesis]

def save_chain(chain):
    with open(BLOCKCHAIN_FILE, "w") as f:
        json.dump(chain, f)

def add_vote(candidate, token_hash):
    chain = load_chain()
    last = chain[-1]
    now = str(datetime.datetime.now())  # <--- время сохраняем в переменную
    new_block = {
        "index": last["index"] + 1,
        "timestamp": now,               # <--- используем сохранённое время
        "data": {"candidate": candidate, "token_hash": token_hash},
        "previous_hash": last["hash"],
        "hash": hashlib.sha256(
            f"{last['index']+1}{last['hash']}{now}{candidate}{token_hash}".encode()  # <--- и здесь то же самое
        ).hexdigest()
    }
    chain.append(new_block)
    save_chain(chain)
    return new_block

def is_valid():
    chain = load_chain()
    for i in range(1, len(chain)):
        if chain[i]["previous_hash"] != chain[i-1]["hash"]:
            return False
        exp = hashlib.sha256(
            f"{chain[i]['index']}{chain[i]['previous_hash']}{chain[i]['timestamp']}{chain[i]['data']['candidate']}{chain[i]['data']['token_hash']}".encode()
        ).hexdigest()
        if exp != chain[i]["hash"]:
            return False
    return True

conn = sqlite3.connect("tokens.db", check_same_thread=False)
c = conn.cursor()
c.execute("CREATE TABLE IF NOT EXISTS tokens (id TEXT PRIMARY KEY, enc TEXT, used INT)")

def gen_token():
    raw = str(uuid.uuid4())[:8]
    enc = cipher.encrypt(raw.encode()).decode()
    tid = str(uuid.uuid4())
    c.execute("INSERT INTO tokens VALUES (?,?,0)", (tid, enc))
    conn.commit()
    return raw

def use_token(token):
    c.execute("SELECT id,enc FROM tokens WHERE used=0")
    rows = c.fetchall()
    for tid, enc in rows:
        try:
            decrypted = cipher.decrypt(enc.encode()).decode()
            if decrypted == token:
                c.execute("UPDATE tokens SET used=1 WHERE id=?", (tid,))
                conn.commit()
                return True
        except Exception:
            continue
    return False

def gen_captcha():
    a = random.randint(1, 9)
    b = random.randint(1, 9)
    session['captcha'] = a + b
    return f"{a} + {b}"

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/register', methods=['GET'])
def register():
    q = gen_captcha()
    return render_template('register.html', captcha_question=q)

@app.route('/do_register', methods=['POST'])
def do_register():
    try:
        user_answer = int(request.form['captcha'])
        if user_answer != session.get('captcha', -1):
            return render_template('message.html', message="Неверная капча", type="error")
    except (ValueError, TypeError):
        return render_template('message.html', message="Неверный формат ответа", type="error")
    token = gen_token()
    return render_template('message.html', message=f"Ваш токен: <strong>{token}</strong><br>Сохраните его для голосования!", type="success")

@app.route('/vote', methods=['GET', 'POST'])
def vote():
    if request.method == 'GET':
        return render_template('vote.html')
    token = request.form['token']
    candidate = request.form['candidate']
    if not use_token(token):
        return render_template('message.html', message="Неверный или уже использованный токен", type="error")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    block = add_vote(candidate, token_hash)
    return render_template('message.html', message=f"Голос принят!<br>Квитанция (хеш блока): <code>{block['hash']}</code><br>Номер блока: {block['index']}", type="success")

@app.route('/results')
def results():
    chain = load_chain()
    votes = {}
    for block in chain[1:]:
        cand = block['data']['candidate']
        votes[cand] = votes.get(cand, 0) + 1
    return render_template('results.html', votes=votes, total=sum(votes.values()))

@app.route('/chain')
def chain_view():
    chain = load_chain()
    valid = is_valid()
    return render_template('chain.html', chain=chain, valid=valid)

@app.route('/api/results')
def api_results():
    chain = load_chain()
    votes = {}
    for block in chain[1:]:
        cand = block['data']['candidate']
        votes[cand] = votes.get(cand, 0) + 1
    return jsonify(votes)

@app.route('/api/chain')
def api_chain():
    chain = load_chain()
    valid = is_valid()
    return jsonify({"chain": chain, "valid": valid})

if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=False, port=8080)