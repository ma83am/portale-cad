import os
import time
import json
import shutil
import zipfile
from datetime import datetime, timedelta
from google.cloud import storage

# --- CONFIGURAZIONE ---
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"secrets\key.json"
BASE_PATH = r"D:\ARCHIVIO CAD"
BUCKET_NAME = "cad-vault-marco"
INBOX_ROOT = os.path.join(BASE_PATH, "0_FILE DA PROCESSARE")

client = storage.Client()
bucket = client.bucket(BUCKET_NAME)

def create_zip(items_list, zip_name, db_components):
    """Crea uno zip temporaneo con tutti i file degli articoli scelti in sottocartelle."""
    os.makedirs(INBOX_ROOT, exist_ok=True)
    temp_zip_path = os.path.join(INBOX_ROOT, f"{zip_name}.zip")
    
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
                            z.write(full_p, arcname=os.path.join(code, file_name))
    return temp_zip_path

def update_heartbeat():
    """Invia il segnale di vita e l'indice aggiornato."""
    try:
        hb = {"last_seen": time.time()}
        bucket.blob("metadata/heartbeat.json").upload_from_string(json.dumps(hb))
        idx_path = os.path.join(BASE_PATH, "archivio.json")
        if os.path.exists(idx_path):
            bucket.blob("metadata/archivio_index.json").upload_from_filename(idx_path)
        print(f"🔄 Heartbeat e Indice sincronizzati: {time.strftime('%H:%M:%S')}")
    except Exception as e: print(f"⚠️ Errore Heartbeat: {e}")

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
            task_type = data.get('type', 'item_zip')
            code = data.get('code')
            items = data.get('items', [code] if code else [])
            
            if task_type in ['item_zip', 'bulk_zip', 'link']:
                zip_name = code if code else f"BULK_{int(time.time())}"
                zip_p = create_zip(items, zip_name, db)
                cloud_path = f"archive/{zip_name}/{zip_name}.zip"
                blob = bucket.blob(cloud_path)
                blob.upload_from_filename(zip_p)
                os.remove(zip_p)
                
                if task_type == 'link':
                    expiration_time = datetime.utcnow() + timedelta(hours=24)
                    link_url = blob.generate_signed_url(expiration=expiration_time)
                    history.insert(0, {"code": zip_name, "type": "link", "url": link_url, "timestamp_sync": time.time()})
                else:
                    history.insert(0, {"code": zip_name, "type": "zip", "formats": ["ZIP"], "timestamp_sync": time.time()})
                
                del queue[task_id]
                updated = True
                print(f"✅ Task completato: {zip_name}.zip")
            
            elif not data.get('synced'):
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
    except Exception as e: print(f"❌ Errore Sync Queue: {e}")

def process_checkin():
    """Scarica i file dal Cloud, li rinomina e li sposta nell'archivio finale."""
    blobs = list(bucket.list_blobs(prefix="inbox/"))
    tasks = [b for b in blobs if b.name.endswith('_task.json')]
    for t_blob in tasks:
        try:
            data = json.loads(t_blob.download_as_text())
            nome = data['nome_articolo']
            # Costruisce il percorso di destinazione finale
            rel_path = data['percorso_relativo'].replace("/", "\\")
            dest_dir = os.path.join(BASE_PATH, rel_path, nome)
            
            print(f"📥 Avvio Check-in: {nome} -> {rel_path}")
            os.makedirs(dest_dir, exist_ok=True)
            
            # Identifica la cartella corretta nel Cloud (dirname del task)
            folder_prefix = os.path.dirname(t_blob.name) + "/"
            
            formats = []
            main_path = ""
            # Cicla su TUTTI i file presenti nella cartella di upload
            for b in blobs:
                if b.name.startswith(folder_prefix) and not b.name.endswith('_task.json'):
                    ext = b.name.split('.')[-1].lower()
                    # RINOMINA FORZATA: nuovo_nome.estensione
                    local_f_path = os.path.join(dest_dir, f"{nome}.{ext}")
                    b.download_to_filename(local_f_path)
                    
                    formats.append(ext.upper())
                    # Identifica il file principale per l'indice
                    if ext.upper() in ['STP', 'STEP', 'IAM', 'ASM', 'DWG', 'SLDPRT']:
                        main_path = local_f_path
                    
                    b.delete() # Rimuove dal cloud dopo il download
                    print(f"   - File scaricato e rinominato: {nome}.{ext}")
            
            if not data.get('solo_trasferimento'):
                idx_path = os.path.join(BASE_PATH, "archivio.json")
                with open(idx_path, 'r+') as f:
                    db_loc = json.load(f)
                    # Rimuove vecchie voci con lo stesso nome
                    db_loc['components'] = [c for c in db_loc.get('components', []) if c['code'] != nome]
                    # Aggiunge la nuova voce con i TAG preservati
                    db_loc['components'].append({
                        "code": nome, 
                        "category": data['percorso_relativo'], 
                        "tags": data['tags'],
                        "formats": list(set(formats)), 
                        "path": main_path if main_path else os.path.join(dest_dir, f"{nome}.{formats[0].lower()}"),
                        "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
                    })
                    f.seek(0); json.dump(db_loc, f, indent=4); f.truncate()
                print(f"✅ Articolo {nome} indicizzato con successo.")
            
            t_blob.delete() # Rimuove il file task alla fine
        except Exception as e: print(f"❌ Errore critico nel Check-in di {t_blob.name}: {e}")

def cleanup_24h():
    """Pulizia automatica file temporanei cloud."""
    h_blob = bucket.blob("metadata/history.json")
    if not h_blob.exists(): return
    try:
        history = json.loads(h_blob.download_as_text())
        new_hist = []; changed = False
        for entry in history:
            if (time.time() - entry['timestamp_sync']) < 86400:
                new_hist.append(entry)
            else:
                blobs = list(bucket.list_blobs(prefix=f"archive/{entry['code']}/"))
                for b in blobs: b.delete()
                changed = True; print(f"🗑️ Scaduto dal Cloud: {entry['code']}")
        if changed: h_blob.upload_from_string(json.dumps(new_hist))
    except Exception as e: print(f"❌ Errore Cleanup: {e}")

if __name__ == "__main__":
    import sys, io
    if sys.platform == "win32": sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("🚀 Bridge 4.5.1 ONLINE (Bulletproof Check-in & Renaming)")
    while True:
        try:
            update_heartbeat()
            process_sync_queue()
            process_checkin()
            cleanup_24h()
        except Exception as e: print(f"⚠️ Errore Ciclo: {e}")
        time.sleep(15)
