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
    """Carica l'indice centrale e l'elenco categorie."""
    index_file = os.path.join(BASE_PATH, "archivio.json")
    if os.path.exists(index_file):
        bucket.blob("metadata/archivio_index.json").upload_from_filename(index_file)
    
    exclude = ['0_FILE DA PROCESSARE', 'scripts', 'procedures', '.streamlit', 'secrets']
    categories = [d for d in os.listdir(BASE_PATH) if os.path.isdir(os.path.join(BASE_PATH, d)) and d not in exclude and not d.startswith('.')]
    bucket.blob("metadata/categories.json").upload_from_string(json.dumps(categories))
    print("🔄 Metadati e categorie sincronizzati.")

def sync_previews(bucket):
    """Carica proattivamente i JPG per rendere le anteprime istantanee."""
    index_path = os.path.join(BASE_PATH, "archivio.json")
    if not os.path.exists(index_path): return
    
    try:
        with open(index_path, 'r') as f:
            db = json.load(f).get('components', [])
        
        for item in db:
            # Cerca se esiste un JPG/PNG tra i formati dichiarati
            img_f = [f for f in item.get('formats', []) if f.upper() in ['JPG', 'PNG', 'JPEG']]
            if img_f:
                ext = img_f[0].lower()
                item_path = item.get('path')
                if not item_path: continue
                
                item_folder = os.path.dirname(item_path)
                local_img = os.path.join(item_folder, f"{item['code']}.{ext}")
                
                if os.path.exists(local_img):
                    cloud_path = f"archive/{item['code']}/{item['code']}.{ext}"
                    blob = bucket.blob(cloud_path)
                    
                    # Carica solo se non esiste già (Risparmio banda!)
                    if not blob.exists():
                        blob.upload_from_filename(local_img)
                        print(f"🖼️ Anteprima caricata: {item['code']}")
    except Exception as e:
        print(f"⚠️ Errore durante sync_previews: {e}")

def process_cloud_inbox(bucket):
    """Gestisce il caricamento di nuovi articoli dal portale."""
    blobs = list(bucket.list_blobs(prefix="inbox/"))
    tasks = [b for b in blobs if b.name.endswith('_task.json')]
    for t_blob in tasks:
        try:
            data = json.loads(t_blob.download_as_text())
            folder_name = data.get('nome_articolo', 'SenzaNome')
            target = os.path.join(INBOX_ROOT, folder_name) if data.get('solo_trasferimento') else os.path.join(CLOUD_INBOX, folder_name)
            os.makedirs(target, exist_ok=True)
            
            prefix = t_blob.name.replace('_task.json', '/')
            for b in blobs:
                if b.name.startswith(prefix):
                    b.download_to_filename(os.path.join(target, os.path.basename(b.name)))
                    b.delete()
            t_blob.download_to_filename(os.path.join(target, f"{folder_name}.json"))
            t_blob.delete()
            print(f"✅ Articolo '{folder_name}' scaricato.")
        except Exception as e:
            print(f"❌ Errore processamento task {t_blob.name}: {e}")

def handle_checkout(bucket):
    """Prepara gli ZIP per il download degli articoli."""
    req_blobs = list(bucket.list_blobs(prefix="requests/"))
    if not req_blobs: return
    
    index_path = os.path.join(BASE_PATH, "archivio.json")
    if not os.path.exists(index_path): return
    
    with open(index_path, 'r') as f:
        db = json.load(f).get('components', [])
        
    for r_blob in req_blobs:
        try:
            req = json.loads(r_blob.download_as_text())
            req_id = req.get('request_id', int(time.time()))
            zip_name = f"Checkout_{req_id}.zip"
            zip_p = os.path.join(INBOX_ROOT, zip_name)
            
            print(f"⚙️ Preparazione ZIP per richiesta {req_id}...")
            with zipfile.ZipFile(zip_p, 'w') as z:
                for code in req['items']:
                    match = next((i for i in db if i['code'] == code), None)
                    if match:
                        item_path = match.get('path')
                        if item_path and os.path.exists(item_path):
                            d = os.path.dirname(item_path)
                            for root, _, files in os.walk(d):
                                for f in files:
                                    fp = os.path.join(root, f)
                                    z.write(fp, os.path.relpath(fp, os.path.dirname(d)))
                                    
            out = bucket.blob(f"downloads/{zip_name}")
            out.upload_from_filename(zip_p)
            url = out.generate_signed_url(version="v4", expiration=600, method="GET")
            bucket.blob(f"responses/{req_id}.json").upload_from_string(json.dumps({"url": url}))
            r_blob.delete()
            print(f"📦 ZIP pronto e link inviato per {req_id}")
        except Exception as e:
            print(f"❌ Errore sessione Checkout: {e}")

def cleanup_previews(bucket, limit_gb=5):
    """Pulisce le anteprime vecchie per non superare la soglia di GB."""
    blobs = list(bucket.list_blobs(prefix="archive/"))
    total_size = sum(b.size for b in blobs)
    limit_bytes = limit_gb * 1024**3
    if total_size > limit_bytes:
        print(f"⚠️ Pulizia anteprime cloud attiva ({total_size / (1024**3):.2f} GB occupati)")
        blobs.sort(key=lambda x: x.time_created)
        current_size = total_size
        for b in blobs:
            if current_size <= limit_bytes: break
            sz = b.size
            b.delete()
            current_size -= sz
            print(f"🗑️ Rimossa anteprima obsoleta: {b.name}")

def handle_urgent_requests(bucket):
    """Controlla se il web ha richiesto file non ancora presenti (Sync Queue)."""
    index_path = os.path.join(BASE_PATH, "archivio.json")
    queue_blob = bucket.blob("metadata/sync_queue.json")
    
    if not queue_blob.exists() or not os.path.exists(index_path): return

    try:
        queue = json.loads(queue_blob.download_as_text())
        with open(index_path, 'r') as f:
            db_locale = json.load(f).get('components', [])
        
        updated = False
        for item_code, details in list(queue.items()):
            # Se non è ancora sincronizzato
            if not details.get('synced', False):
                # Cerchiamo l'articolo nel database locale
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
                    print(f"⚡ Sincronizzazione URGENTE completata: {item_code}")

        if updated:
            queue_blob.upload_from_string(json.dumps(queue))
    except Exception as e:
        print(f"⚠️ Errore handle_urgent_requests: {e}")

if __name__ == "__main__":
    # Garantisco compatibilità UTF8 per le emoji nei log Windows
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        
    print("🚀 Bridge 3.2 Operativo (Proactive Preview Engine)")
    
    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
    except Exception as e:
        print(f"❌ Errore GCS Client: {e}")
        sys.exit(1)
        
    while True:
        try:
            update_remote_metadata(bucket)
            sync_previews(bucket) # Analisi e upload automatico anteprime
            process_cloud_inbox(bucket)
            handle_checkout(bucket)
            handle_urgent_requests(bucket) # Smistamento richieste prioritarie dal web
            cleanup_previews(bucket, 5)
            
            # Invia il segnale di vita (Heartbeat) per il monitoraggio remoto
            heartbeat_data = {"last_seen": time.time(), "status": "online"}
            bucket.blob("metadata/heartbeat.json").upload_from_string(json.dumps(heartbeat_data))
            print("💓 Heartbeat inviato.")
        except Exception as e:
            print(f"❌ Errore nel ciclo di lavoro: {e}")
        
        time.sleep(30)
