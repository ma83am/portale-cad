import os
import time
import json
import shutil
import zipfile
from google.cloud import storage

# --- CONFIGURAZIONE ---
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"secrets\key.json"
BUCKET_NAME = "cad-vault-marco"
BASE_PATH = r"D:\ARCHIVIO CAD"
INBOX_ROOT = os.path.join(BASE_PATH, "0_FILE DA PROCESSARE")
CLOUD_INBOX = os.path.join(INBOX_ROOT, "CLOUD_INBOX")

client = storage.Client()
bucket = client.bucket(BUCKET_NAME)

def update_heartbeat():
    """Invia il segnale di vita e l'indice aggiornato."""
    hb = {"last_seen": time.time()}
    bucket.blob("metadata/heartbeat.json").upload_from_string(json.dumps(hb))
    
    idx_path = os.path.join(BASE_PATH, "archivio.json")
    if os.path.exists(idx_path):
        bucket.blob("metadata/archivio_index.json").upload_from_filename(idx_path)
    print(f"🔄 Heartbeat e Indice sincronizzati: {time.strftime('%H:%M:%S')}")

def process_sync_queue():
    """Preleva richieste urgenti dal web e le carica nel Cloud."""
    q_blob = bucket.blob("metadata/sync_queue.json")
    if not q_blob.exists(): return
    
    try:
        queue = json.loads(q_blob.download_as_text())
        h_blob = bucket.blob("metadata/history.json")
        history = json.loads(h_blob.download_as_text()) if h_blob.exists() else []
        
        updated = False
        idx_path = os.path.join(BASE_PATH, "archivio.json")
        if not os.path.exists(idx_path): return
        
        with open(idx_path, 'r') as f:
            db = json.load(f).get('components', [])

        for code, data in list(queue.items()):
            if not data.get('synced', False):
                item = next((i for i in db if i['code'] == code), None)
                if item:
                    item_path = item.get('path')
                    if not item_path: continue
                    
                    folder = os.path.dirname(item_path)
                    # Carica tutti i formati disponibili per quel pezzo
                    for fmt in item['formats']:
                        local_f = os.path.join(folder, f"{code}.{fmt.lower()}")
                        if os.path.exists(local_f):
                            bucket.blob(f"archive/{code}/{code}.{fmt.lower()}").upload_from_filename(local_f)
                    
                    # Rimuovi dalla coda e sposta in History con timer 24h
                    del queue[code]
                    # Rimuovi eventuali duplicati nella history prima di inserire
                    history = [h for h in history if h['code'] != code]
                    history.insert(0, {
                        "code": code, 
                        "timestamp_sync": time.time(),
                        "category": item['category']
                    })
                    updated = True
                    print(f"⚡ Sincronizzato e messo in cronologia: {code}")

        if updated:
            q_blob.upload_from_string(json.dumps(queue))
            h_blob.upload_from_string(json.dumps(history[:20])) # Tieni ultimi 20
    except Exception as e:
        print(f"❌ Errore Sync Queue: {e}")

def cleanup_24h():
    """Rimuove file dal cloud e dalla history dopo 24 ore."""
    h_blob = bucket.blob("metadata/history.json")
    if not h_blob.exists(): return
    
    try:
        history = json.loads(h_blob.download_as_text())
        now = time.time()
        new_history = []
        changed = False

        for item in history:
            # 86400 secondi = 24 ore
            if (now - item['timestamp_sync']) < 86400:
                new_history.append(item)
            else:
                # CANCELLAZIONE DAL CLOUD
                code = item['code']
                blobs = list(bucket.list_blobs(prefix=f"archive/{code}/"))
                for b in blobs:
                    b.delete()
                changed = True
                print(f"🗑️ Scaduto: {code} rimosso dal Cloud.")

        if changed:
            h_blob.upload_from_string(json.dumps(new_history))
    except Exception as e:
        print(f"❌ Errore Cleanup: {e}")

def process_checkin():
    """Scarica i file dal Cloud e li archivia nelle cartelle fisiche."""
    blobs = list(bucket.list_blobs(prefix="inbox/"))
    tasks = [b for b in blobs if b.name.endswith('_task.json')]
    
    for t_blob in tasks:
        try:
            data = json.loads(t_blob.download_as_text())
            nome = data['nome_articolo']
            rel_path = data['percorso_relativo'].replace("/", "\\")
            dest_dir = os.path.join(BASE_PATH, rel_path, nome)
            
            if data.get('solo_trasferimento'):
                dest_dir = os.path.join(INBOX_ROOT, nome)

            os.makedirs(dest_dir, exist_ok=True)
            
            # Scarica file reali
            prefix = t_blob.name.replace('_task.json', '')
            formats = []
            main_path = ""
            for b in blobs:
                if b.name.startswith(prefix) and not b.name.endswith('_task.json'):
                    # Ottieni l'estensione originale
                    orig_ext = b.name.split('.')[-1]
                    local_path = os.path.join(dest_dir, f"{nome}.{orig_ext.lower()}")
                    b.download_to_filename(local_path)
                    formats.append(orig_ext.upper())
                    if orig_ext.upper() in ['STP', 'STEP', 'IAM', 'ASM', 'DWG', 'SLDPRT']:
                        main_path = local_path
                    b.delete()
            
            # Aggiorna archivio.json se non è solo trasferimento
            if not data.get('solo_trasferimento'):
                idx_path = os.path.join(BASE_PATH, "archivio.json")
                if os.path.exists(idx_path):
                    with open(idx_path, 'r+') as f:
                        db = json.load(f)
                        db['components'] = [c for c in db.get('components', []) if c['code'] != nome]
                        db['components'].append({
                            "code": nome, 
                            "category": data['percorso_relativo'],
                            "tags": data.get('tags', []), 
                            "formats": list(set(formats)),
                            "path": main_path if main_path else os.path.join(dest_dir, f"{nome}.{formats[0].lower()}"),
                            "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
                        })
                        f.seek(0); json.dump(db, f, indent=4); f.truncate()
            
            t_blob.delete()
            print(f"📥 Check-in completato: {nome}")
        except Exception as e:
            print(f"❌ Errore Check-in: {e}")

if __name__ == "__main__":
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        
    print("🚀 Bridge 4.0 ONLINE (Cloud 24h & History Mode)")
    while True:
        try:
            update_heartbeat()
            process_sync_queue()
            process_checkin()
            cleanup_24h()
        except Exception as e:
            print(f"⚠️ Errore Ciclo: {e}")
        time.sleep(30)
