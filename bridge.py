import os
import time
import json
import shutil
import zipfile
from google.cloud import storage

# --- CONFIGURAZIONE ---
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"secrets\key.json"
BASE_PATH = r"D:\ARCHIVIO CAD"
BUCKET_NAME = "cad-vault-marco"
INBOX_ROOT = os.path.join(BASE_PATH, "0_FILE DA PROCESSARE")

client = storage.Client()
bucket = client.bucket(BUCKET_NAME)

def create_zip(items_list, zip_name, db_components):
    """Crea uno zip temporaneo con tutti i formati degli articoli scelti."""
    temp_zip_path = os.path.join(INBOX_ROOT, f"{zip_name}.zip")
    os.makedirs(INBOX_ROOT, exist_ok=True)
    
    with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for code in items_list:
            item = next((i for i in db_components if i['code'] == code), None)
            if item:
                item_path = item.get('path')
                if item_path:
                    folder = os.path.dirname(item_path)
                    for fmt in item['formats']:
                        file_name = f"{code}.{fmt.lower()}"
                        full_p = os.path.join(folder, file_name)
                        if os.path.exists(full_p):
                            # Mette i file in una cartella col nome del codice dentro lo ZIP
                            z.write(full_p, arcname=os.path.join(code, file_name))
    return temp_zip_path

def update_heartbeat():
    """Invia il segnale di vita e l'indice aggiornato."""
    hb = {"last_seen": time.time()}
    bucket.blob("metadata/heartbeat.json").upload_from_string(json.dumps(hb))
    idx_path = os.path.join(BASE_PATH, "archivio.json")
    if os.path.exists(idx_path):
        bucket.blob("metadata/archivio_index.json").upload_from_filename(idx_path)
    print(f"🔄 Heartbeat e Indice sincronizzati: {time.strftime('%H:%M:%S')}")

def process_sync_queue():
    """Gestisce la coda di sincronizzazione (ZIP, Bulk, Link, Formati)."""
    q_blob = bucket.blob("metadata/sync_queue.json")
    if not q_blob.exists(): return
    
    try:
        queue = json.loads(q_blob.download_as_text())
        h_blob = bucket.blob("metadata/history.json")
        history = json.loads(h_blob.download_as_text()) if h_blob.exists() else []
        
        idx_path = os.path.join(BASE_PATH, "archivio.json")
        if not os.path.exists(idx_path): return
        with open(idx_path, 'r') as f:
            db = json.load(f).get('components', [])

        updated = False
        for task_id, data in list(queue.items()):
            # La coda può contenere vecchie entry (code: {synced...}) o nuove (task_id: {type...})
            task_type = data.get('type', 'item_zip')
            code = data.get('code')
            items = data.get('items', [code] if code else [])
            
            print(f"🛠️ Elaborazione Task {task_id}: {task_type} per {code if code else items}")

            if task_type in ['item_zip', 'bulk_zip', 'link']:
                # Creazione ZIP
                zip_name = code if code else f"BULK_{int(time.time())}"
                zip_p = create_zip(items, zip_name, db)
                
                cloud_path = f"archive/{zip_name}/{zip_name}.zip"
                blob = bucket.blob(cloud_path)
                blob.upload_from_filename(zip_p)
                os.remove(zip_p)
                
                if task_type == 'link':
                    # Genera Signed URL valido 24h
                    url = blob.generate_signed_url(expiration=86400)
                    history.insert(0, {
                        "code": zip_name, "type": "link", "url": url, 
                        "timestamp_sync": time.time(), "items": items
                    })
                else:
                    history.insert(0, {
                        "code": zip_name, "type": "zip", "formats": ["ZIP"], 
                        "timestamp_sync": time.time(), "items": items
                    })
                
                del queue[task_id]
                updated = True
                print(f"✅ Task completato: {zip_name}.zip")
            
            elif not data.get('synced'): # Vecchia logica compatibilità
                # ... (Logica caricamento formati singoli v4.2) ...
                item = next((i for i in db if i['code'] == code), None)
                if item:
                    folder = os.path.dirname(item['path'])
                    synced_fmts = []
                    for fmt in data.get('formats', []):
                        local_f = os.path.join(folder, f"{code}.{fmt.lower()}")
                        if os.path.exists(local_f):
                            bucket.blob(f"archive/{code}/{code}.{fmt.lower()}").upload_from_filename(local_f)
                            synced_fmts.append(fmt)
                    del queue[task_id]
                    history.insert(0, {"code": code, "formats": synced_fmts, "timestamp_sync": time.time(), "category": item['category']})
                    updated = True

        if updated:
            q_blob.upload_from_string(json.dumps(queue))
            h_blob.upload_from_string(json.dumps(history[:25]))
    except Exception as e:
        print(f"❌ Errore Sync Queue: {e}")

def process_checkin():
    """Scarica i file dal Cloud e li archivia."""
    blobs = list(bucket.list_blobs(prefix="inbox/"))
    tasks = [b for b in blobs if b.name.endswith('_task.json')]
    for t_blob in tasks:
        try:
            data = json.loads(t_blob.download_as_text())
            nome = data['nome_articolo']
            dest_dir = os.path.join(BASE_PATH, data['percorso_relativo'].replace("/", "\\"), nome)
            os.makedirs(dest_dir, exist_ok=True)
            prefix = t_blob.name.replace('_task.json', '')
            formats = []
            main_path = ""
            for b in blobs:
                if b.name.startswith(prefix) and not b.name.endswith('_task.json'):
                    ext = b.name.split('.')[-1].lower()
                    local_f = os.path.join(dest_dir, f"{nome}.{ext}")
                    b.download_to_filename(local_f)
                    formats.append(ext.upper())
                    if ext.upper() in ['STP', 'STEP', 'IAM', 'ASM', 'DWG', 'SLDPRT']: main_path = local_f
                    b.delete()
            if not data.get('solo_trasferimento'):
                idx_path = os.path.join(BASE_PATH, "archivio.json")
                with open(idx_path, 'r+') as f:
                    db_loc = json.load(f)
                    db_loc['components'] = [c for c in db_loc.get('components', []) if c['code'] != nome]
                    db_loc['components'].append({
                        "code": nome, "category": data['percorso_relativo'], "tags": data['tags'],
                        "formats": list(set(formats)), "path": main_path if main_path else os.path.join(dest_dir, f"{nome}.{formats[0].lower()}"),
                        "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
                    })
                    f.seek(0); json.dump(db_loc, f, indent=4); f.truncate()
            t_blob.delete()
            print(f"📥 Archiviato: {nome}")
        except Exception as e: print(f"❌ Errore Check-in: {e}")

def cleanup_24h():
    """Pulizia file scaduti."""
    h_blob = bucket.blob("metadata/history.json")
    if not h_blob.exists(): return
    try:
        history = json.loads(h_blob.download_as_text())
        new_hist = []
        changed = False
        for entry in history:
            if (time.time() - entry['timestamp_sync']) < 86400:
                new_hist.append(entry)
            else:
                blobs = list(bucket.list_blobs(prefix=f"archive/{entry['code']}/"))
                for b in blobs: b.delete()
                changed = True
                print(f"🗑️ Scaduto: {entry['code']}")
        if changed: h_blob.upload_from_string(json.dumps(new_hist))
    except Exception as e: print(f"❌ Errore Cleanup: {e}")

if __name__ == "__main__":
    import sys, io
    if sys.platform == "win32": sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("🚀 Bridge 4.3 ONLINE (Bulk & Share Link Ready)")
    while True:
        try:
            update_heartbeat()
            process_sync_queue()
            process_checkin()
            cleanup_24h()
        except Exception as e: print(f"⚠️ Errore Ciclo: {e}")
        time.sleep(15)
