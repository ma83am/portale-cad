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

def update_remote_metadata(bucket):
    """Crea una mappa dinamica Main_Folder -> [Sub_Folders] e invia Heartbeat."""
    exclude = ['0_FILE DA PROCESSARE', 'scripts', 'procedures', '.streamlit', 'secrets']
    category_map = {}
    
    if not os.path.exists(BASE_PATH):
        print(f"⚠️ BASE_PATH non trovato: {BASE_PATH}")
        return

    for d in os.listdir(BASE_PATH):
        full_path = os.path.join(BASE_PATH, d)
        if os.path.isdir(full_path) and d not in exclude and not d.startswith('.'):
            # Cerca sottocartelle reali (es. in 4_COMMERCIALI)
            subs = [s for s in os.listdir(full_path) 
                    if os.path.isdir(os.path.join(full_path, s)) and not s.startswith('.')]
            category_map[d] = subs
            
    bucket.blob("metadata/categories.json").upload_from_string(json.dumps(category_map))
    # Heartbeat integrato
    bucket.blob("metadata/heartbeat.json").upload_from_string(json.dumps({"last_seen": time.time()}))
    print(f"🔄 Mappa categorie ({len(category_map)} main) e Heartbeat sincronizzati.")

def archive_new_item(temp_folder, nome, categoria_completa, tags):
    """Sposta i file dal CLOUD_INBOX alla cartella finale e aggiorna l'indice."""
    # categoria_completa può essere "4_COMMERCIALI/A CATALOGO" o "1_ASSIEMI"
    dest_dir = os.path.join(BASE_PATH, categoria_completa.replace("/", "\\"), nome)
    os.makedirs(dest_dir, exist_ok=True)
    
    formats = []
    main_file_path = ""
    
    for f in os.listdir(temp_folder):
        if f.endswith('.json'): continue
        
        ext = f.split('.')[-1].upper()
        nuovo_nome = f"{nome}.{ext.lower()}"
        source_f = os.path.join(temp_folder, f)
        dest_f = os.path.join(dest_dir, nuovo_nome)
        
        try:
            shutil.move(source_f, dest_f)
            formats.append(ext)
            if ext in ['STP', 'STEP', 'IAM', 'ASM', 'DWG', 'SLDPRT']:
                main_file_path = dest_f
        except Exception as e:
            print(f"⚠️ Errore spostamento {f}: {e}")
            
    # Aggiorna il file archivio.json locale
    idx_path = os.path.join(BASE_PATH, "archivio.json")
    if os.path.exists(idx_path):
        try:
            with open(idx_path, 'r+') as f:
                db = json.load(f)
                # Rimuovi entry esistenti
                db['components'] = [c for c in db.get('components', []) if c['code'] != nome]
                
                db['components'].append({
                    "code": nome,
                    "category": categoria_completa,
                    "tags": [t.strip() for t in tags.split(',')] if isinstance(tags, str) else tags,
                    "formats": list(set(formats)),
                    "path": main_file_path,
                    "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
                })
                f.seek(0)
                json.dump(db, f, indent=4)
                f.truncate()
            print(f"✅ Archiviato: {nome} in {categoria_completa}")
        except Exception as e:
            print(f"❌ Errore aggiornamento indice: {e}")
    
    return dest_dir

def sync_previews(bucket):
    """Carica proattivamente i JPG per le anteprime."""
    index_path = os.path.join(BASE_PATH, "archivio.json")
    if not os.path.exists(index_path): return
    try:
        with open(index_path, 'r') as f:
            db = json.load(f).get('components', [])
        for item in db:
            img_f = [f for f in item.get('formats', []) if f.upper() in ['JPG', 'PNG', 'JPEG']]
            if img_f:
                ext = img_f[0].lower()
                item_p = item.get('path')
                if not item_p: continue
                local_img = os.path.join(os.path.dirname(item_p), f"{item['code']}.{ext}")
                if os.path.exists(local_img):
                    cloud_p = f"archive/{item['code']}/{item['code']}.{ext}"
                    blob = bucket.blob(cloud_p)
                    if not blob.exists():
                        blob.upload_from_filename(local_img)
                        print(f"🖼️ Anteprima caricata: {item['code']}")
    except Exception as e: print(f"⚠️ Errore sync_previews: {e}")

def process_cloud_inbox(bucket):
    """Gestisce il caricamento e l'archiviazione automatica."""
    blobs = list(bucket.list_blobs(prefix="inbox/"))
    tasks = [b for b in blobs if b.name.endswith('_task.json')]
    for t_blob in tasks:
        try:
            data = json.loads(t_blob.download_as_text())
            nome = data.get('nome_articolo', 'SenzaNome')
            categoria = data.get('categoria', 'NON_CATEGORIZZATO')
            tags = data.get('tags', [])
            solo_trasferimento = data.get('solo_trasferimento', False)
            
            temp_path = os.path.join(INBOX_ROOT, "TEMP_" + nome)
            os.makedirs(temp_path, exist_ok=True)
            
            prefix = t_blob.name.replace('_task.json', '/')
            for b in blobs:
                if b.name.startswith(prefix):
                    b.download_to_filename(os.path.join(temp_path, os.path.basename(b.name)))
                    b.delete()
            
            if solo_trasferimento:
                final_inbox = os.path.join(CLOUD_INBOX, nome)
                os.makedirs(final_inbox, exist_ok=True)
                for f in os.listdir(temp_path):
                    shutil.move(os.path.join(temp_path, f), os.path.join(final_inbox, f))
                shutil.rmtree(temp_path)
                print(f"🚚 Articolo {nome} parcheggiato in CLOUD_INBOX.")
            else:
                archive_new_item(temp_path, nome, categoria, ", ".join(tags) if isinstance(tags, list) else tags)
                shutil.rmtree(temp_path)
                
            t_blob.delete()
        except Exception as e: print(f"❌ Errore process_cloud_inbox: {e}")

def handle_checkout(bucket):
    """Prepara gli ZIP per il download."""
    req_blobs = list(bucket.list_blobs(prefix="requests/"))
    if not req_blobs: return
    idx_path = os.path.join(BASE_PATH, "archivio.json")
    if not os.path.exists(idx_path): return
    try:
        with open(idx_path, 'r') as f:
            db = json.load(f).get('components', [])
        for r_blob in req_blobs:
            req = json.loads(r_blob.download_as_text())
            req_id = req.get('request_id', int(time.time()))
            zip_name = f"Checkout_{req_id}.zip"
            zip_p = os.path.join(INBOX_ROOT, zip_name)
            with zipfile.ZipFile(zip_p, 'w') as z:
                for code in req['items']:
                    match = next((i for i in db if i['code'] == code), None)
                    if match:
                        item_p = match.get('path')
                        if item_p and os.path.exists(item_p):
                            d = os.path.dirname(item_p)
                            for root, _, files in os.walk(d):
                                for f in files:
                                    fp = os.path.join(root, f)
                                    z.write(fp, os.path.relpath(fp, os.path.dirname(d)))
            out = bucket.blob(f"downloads/{zip_name}")
            out.upload_from_filename(zip_p)
            url = out.generate_signed_url(version="v4", expiration=600, method="GET")
            bucket.blob(f"responses/{req_id}.json").upload_from_string(json.dumps({"url": url}))
            r_blob.delete()
            print(f"📦 ZIP pronto per {req_id}")
    except Exception as e: print(f"❌ Errore handle_checkout: {e}")

def handle_urgent_requests(bucket):
    """Sincronizzazione prioritaria per richieste web."""
    index_path = os.path.join(BASE_PATH, "archivio.json")
    queue_blob = bucket.blob("metadata/sync_queue.json")
    if not queue_blob.exists() or not os.path.exists(index_path): return
    try:
        queue = json.loads(queue_blob.download_as_text())
        with open(index_path, 'r') as f:
            db_locale = json.load(f).get('components', [])
        updated = False
        for item_code, details in list(queue.items()):
            if not details.get('synced', False):
                match = next((i for i in db_locale if i['code'] == item_code), None)
                if match:
                    folder = os.path.dirname(match['path'])
                    for fmt in details.get('formats', []):
                        local_f = os.path.join(folder, f"{item_code}.{fmt.lower()}")
                        if os.path.exists(local_f):
                            cloud_p = f"archive/{item_code}/{item_code}.{fmt.lower()}"
                            bucket.blob(cloud_p).upload_from_filename(local_f)
                    queue[item_code]['synced'] = True
                    updated = True
                    print(f"⚡ Sincronizzazione URGENTE: {item_code}")
        if updated: queue_blob.upload_from_string(json.dumps(queue))
    except Exception as e: print(f"⚠️ Errore handle_urgent_requests: {e}")

def cleanup_previews(bucket, limit_gb=5):
    """Pulisce anteprime vecchie."""
    blobs = list(bucket.list_blobs(prefix="archive/"))
    total_size = sum(b.size for b in blobs)
    limit_bytes = limit_gb * 1024**3
    if total_size > limit_bytes:
        blobs.sort(key=lambda x: x.time_created)
        current_size = total_size
        for b in blobs:
            if current_size <= limit_bytes: break
            sz = b.size
            b.delete()
            current_size -= sz
            print(f"🗑️ Pulizia: {b.name}")

if __name__ == "__main__":
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    print("🚀 Bridge 3.4 Operativo (Cascading Categories Map)...")
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    while True:
        try:
            update_remote_metadata(bucket)
            sync_previews(bucket)
            process_cloud_inbox(bucket)
            handle_checkout(bucket)
            handle_urgent_requests(bucket)
            cleanup_previews(bucket, 5)
        except Exception as e: print(f"❌ Errore nel ciclo: {e}")
        time.sleep(30)
