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
    """Scansiona categorie e sottocartelle (es. COMMERCIALI/A CATALOGO)."""
    exclude = ['0_FILE DA PROCESSARE', 'scripts', 'procedures', '.streamlit', 'secrets']
    categories = []
    
    if not os.path.exists(BASE_PATH):
        print(f"⚠️ Percorso BASE_PATH non trovato: {BASE_PATH}")
        return

    for d in os.listdir(BASE_PATH):
        full_d = os.path.join(BASE_PATH, d)
        if os.path.isdir(full_d) and d not in exclude and not d.startswith('.'):
            # Aggiunge la cartella principale
            categories.append(d)
            # Cerca sottocartelle (es. per 4_COMMERCIALI)
            try:
                for sub in os.listdir(full_d):
                    sub_p = os.path.join(full_d, sub)
                    if os.path.isdir(sub_p) and not sub.startswith('.'):
                        categories.append(f"{d}/{sub}")
            except:
                pass
    
    bucket.blob("metadata/categories.json").upload_from_string(json.dumps(categories))
    print(f"🔄 Metadati e {len(categories)} categorie sincronizzati.")

def archive_new_item(folder_path, nome_articolo, categoria, tags):
    """Sposta i file nella destinazione finale e aggiorna l'indice archivio.json."""
    # Destinazione: D:\ARCHIVIO CAD\CATEGORIA\CODICE
    dest_dir = os.path.join(BASE_PATH, categoria.replace('/', os.sep), nome_articolo)
    os.makedirs(dest_dir, exist_ok=True)
    
    formats = []
    main_path = ""
    
    for f in os.listdir(folder_path):
        if f.endswith('.json'): continue # Salta il task file
        
        ext = f.split('.')[-1].upper()
        new_name = f"{nome_articolo}.{ext.lower()}"
        source_f = os.path.join(folder_path, f)
        dest_f = os.path.join(dest_dir, new_name)
        
        try:
            shutil.move(source_f, dest_f)
            formats.append(ext)
            # Identifica il file principale (3D)
            if ext in ['STP', 'STEP', 'IAM', 'ASM', 'SLDPRT']:
                main_path = dest_f
        except Exception as e:
            print(f"⚠️ Errore spostamento {f}: {e}")
    
    # Se non c'è un file 3D, prendi il primo disponibile come path di riferimento
    if not main_path and os.listdir(dest_dir):
        main_path = os.path.join(dest_dir, os.listdir(dest_dir)[0])

    # Aggiornamento Indice Locale
    idx_path = os.path.join(BASE_PATH, "archivio.json")
    if os.path.exists(idx_path):
        try:
            with open(idx_path, 'r+') as f:
                data = json.load(f)
                # Rimuovi eventuali entry esistenti con lo stesso codice per evitare duplicati
                data['components'] = [c for c in data.get('components', []) if c['code'] != nome_articolo]
                
                new_entry = {
                    "code": nome_articolo,
                    "category": categoria,
                    "tags": [t.strip() for t in tags.split(',')] if isinstance(tags, str) else tags,
                    "formats": list(set(formats)),
                    "path": main_path,
                    "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
                }
                data['components'].append(new_entry)
                f.seek(0)
                json.dump(data, f, indent=4)
                f.truncate()
            print(f"📝 Indice aggiornato per {nome_articolo}")
        except Exception as e:
            print(f"❌ Errore aggiornamento indice: {e}")
    
    return dest_dir

def sync_previews(bucket):
    """Carica proattivamente i JPG per rendere le anteprime istantanee."""
    index_path = os.path.join(BASE_PATH, "archivio.json")
    if not os.path.exists(index_path): return
    
    try:
        with open(index_path, 'r') as f:
            db = json.load(f).get('components', [])
        
        for item in db:
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
                    if not blob.exists():
                        blob.upload_from_filename(local_img)
                        print(f"🖼️ Anteprima caricata: {item['code']}")
    except Exception as e:
        print(f"⚠️ Errore sync_previews: {e}")

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
            
            # Percorso temporaneo per il download
            temp_path = os.path.join(INBOX_ROOT, "TEMP_" + nome)
            os.makedirs(temp_path, exist_ok=True)
            
            # Download file del batch
            prefix = t_blob.name.replace('_task.json', '/')
            for b in blobs:
                if b.name.startswith(prefix):
                    b.download_to_filename(os.path.join(temp_path, os.path.basename(b.name)))
                    b.delete()
            
            if solo_trasferimento:
                # Sposta semplicemente in CLOUD_INBOX
                final_inbox = os.path.join(CLOUD_INBOX, nome)
                os.makedirs(final_inbox, exist_ok=True)
                for f in os.listdir(temp_path):
                    shutil.move(os.path.join(temp_path, f), os.path.join(final_inbox, f))
                shutil.rmtree(temp_path)
                print(f"🚚 Articolo {nome} parcheggiato in CLOUD_INBOX.")
            else:
                # Esegui archiviazione automatica
                archive_new_item(temp_path, nome, categoria, ", ".join(tags) if isinstance(tags, list) else tags)
                shutil.rmtree(temp_path)
                print(f"📦 Articolo {nome} archiviato in {categoria}")
                
            t_blob.delete()
        except Exception as e:
            print(f"❌ Errore process_cloud_inbox: {e}")

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
            print(f"📦 ZIP pronto per richiesta {req_id}")
    except Exception as e:
        print(f"❌ Errore handle_checkout: {e}")

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

        if updated:
            queue_blob.upload_from_string(json.dumps(queue))
    except Exception as e:
        print(f"⚠️ Errore handle_urgent_requests: {e}")

def cleanup_previews(bucket, limit_gb=5):
    """Mantiene lo spazio cloud sotto controllo."""
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
        
    print("🚀 Bridge 3.3 Operativo (Auto-Archive Engine)")
    
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
        
    while True:
        try:
            update_remote_metadata(bucket)
            sync_previews(bucket)
            process_cloud_inbox(bucket)
            handle_checkout(bucket)
            handle_urgent_requests(bucket)
            
            heartbeat_data = {"last_seen": time.time(), "status": "online"}
            bucket.blob("metadata/heartbeat.json").upload_from_string(json.dumps(heartbeat_data))
            
            cleanup_previews(bucket, 5)
        except Exception as e:
            print(f"❌ Errore: {e}")
        
        time.sleep(30)
