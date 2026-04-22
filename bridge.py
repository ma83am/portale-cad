import os
import time
import json
import shutil
import zipfile
from google.cloud import storage

# --- CONFIGURAZIONE ---
# Assicurati che il percorso della chiave sia corretto sul tuo PC
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"secrets\key.json"
BUCKET_NAME = "cad-vault-marco"
BASE_PATH = r"D:\ARCHIVIO CAD"
INBOX_ROOT = os.path.join(BASE_PATH, "0_FILE DA PROCESSARE")
CLOUD_INBOX = os.path.join(INBOX_ROOT, "CLOUD_INBOX")

def update_remote_metadata(bucket):
    """Sincronizza l'indice locale e le categorie con il Cloud."""
    # 1. Caricamento Indice Centrale
    index_file = os.path.join(BASE_PATH, "archivio.json")
    if os.path.exists(index_file):
        bucket.blob("metadata/archivio_index.json").upload_from_filename(index_file)
    
    # 2. Scansione Categorie (Cartelle reali su D:)
    # Escludiamo cartelle tecniche o di sistema
    exclude = ['0_FILE DA PROCESSARE', 'scripts', 'procedures', '.streamlit', 'secrets']
    categories = [d for d in os.listdir(BASE_PATH) 
                  if os.path.isdir(os.path.join(BASE_PATH, d)) and d not in exclude and not d.startswith('.')]
    
    bucket.blob("metadata/categories.json").upload_from_string(json.dumps(categories))
    print("🔄 Metadati e categorie sincronizzati.")

def process_cloud_inbox(bucket):
    """Scarica i nuovi file dal portale e li smista in base al flag."""
    blobs = list(bucket.list_blobs(prefix="inbox/"))
    # Cerchiamo i file di task che contengono le istruzioni
    tasks = [b for b in blobs if b.name.endswith('_task.json')]
    
    for t_blob in tasks:
        try:
            data = json.loads(t_blob.download_as_text())
            is_manual = data.get('solo_trasferimento', False)
            folder_name = data.get('nome_articolo', 'SenzaNome')
            
            # SMISTAMENTO:
            # True -> Va in una sottocartella nel parcheggio manuale
            # False -> Va nella corsia CLOUD_INBOX per l'Agente Archivista
            if is_manual:
                target = os.path.join(INBOX_ROOT, folder_name)
            else:
                target = os.path.join(CLOUD_INBOX, folder_name)
                
            os.makedirs(target, exist_ok=True)
            
            # Scarica i file associati a questo specifico articolo
            prefix = t_blob.name.replace('_task.json', '/')
            for b in blobs:
                if b.name.startswith(prefix):
                    local_filename = os.path.basename(b.name)
                    b.download_to_filename(os.path.join(target, local_filename))
                    b.delete() # Pulizia Cloud
            
            # Scarica il file JSON dei metadati (utile per l'Archivista)
            t_blob.download_to_filename(os.path.join(target, f"{folder_name}.json"))
            t_blob.delete()
            print(f"✅ Articolo '{folder_name}' scaricato in: {target}")
        except Exception as e:
            print(f"❌ Errore processamento task {t_blob.name}: {e}")

def handle_checkout_requests(bucket):
    """Gestisce le richieste di download generate dal Checkout web."""
    req_blobs = list(bucket.list_blobs(prefix="requests/"))
    index_file = os.path.join(BASE_PATH, "archivio.json")
    
    if not req_blobs or not os.path.exists(index_file):
        return

    with open(index_file, 'r') as f:
        db = json.load(f).get('components', [])

    for r_blob in req_blobs:
        try:
            req = json.loads(r_blob.download_as_text())
            req_id = req['request_id']
            zip_name = f"Checkout_{req_id}.zip"
            zip_path = os.path.join(INBOX_ROOT, zip_name)
            
            print(f"⚙️ Preparazione ZIP per richiesta {req_id}...")
            # Creazione dello ZIP cercando i file nei percorsi dell'indice
            with zipfile.ZipFile(zip_path, 'w') as z:
                for item_code in req['items']:
                    # Cerca l'articolo nel database locale
                    match = next((i for i in db if i['code'] == item_code), None)
                    if match:
                        item_path = match.get('path')
                        if item_path and os.path.exists(item_path):
                            item_dir = os.path.dirname(item_path)
                            for root, _, files in os.walk(item_dir):
                                for file in files:
                                    full_p = os.path.join(root, file)
                                    # Mantiene la struttura delle cartelle nello ZIP
                                    z.write(full_p, os.path.relpath(full_p, os.path.dirname(item_dir)))
            
            # Carica lo ZIP e genera link temporaneo (10 min)
            out_blob = bucket.blob(f"downloads/{zip_name}")
            out_blob.upload_from_filename(zip_path)
            url = out_blob.generate_signed_url(version="v4", expiration=600, method="GET")
            
            # Risposta per il portale
            bucket.blob(f"responses/{req_id}.json").upload_from_string(json.dumps({"url": url}))
            r_blob.delete()
            print(f"📦 ZIP generato per richiesta {req_id}")
        except Exception as e:
            print(f"❌ Errore Checkout: {e}")

def cleanup_cloud_storage(bucket, limit_gb=5):
    """Mantiene lo spazio delle anteprime (archive/) sotto la soglia stabilita."""
    blobs = list(bucket.list_blobs(prefix="archive/"))
    total_size = sum(b.size for b in blobs)
    limit_bytes = limit_gb * 1024 * 1024 * 1024
    
    if total_size > limit_bytes:
        print(f"⚠️ Pulizia necessaria: {total_size / (1024**3):.2f} GB occupati.")
        # Ordina per data creazione (FIFO: cancella i più vecchi)
        blobs.sort(key=lambda x: x.time_created)
        
        current_size = total_size
        for blob in blobs:
            if current_size <= limit_bytes:
                break
            sz = blob.size
            blob.delete()
            current_size -= sz
            print(f"🗑️ Rimossa anteprima vecchia: {blob.name}")

if __name__ == "__main__":
    # Garantisco compatibilità UTF8 per le emoji nei log Windows
    import sys
    import io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        
    print("🚀 Bridge 3.1 Operativo (PC Locale H24)")
    
    try:
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
    except Exception as e:
        print(f"❌ Errore inizializzazione client GCS: {e}")
        sys.exit(1)
    
    while True:
        try:
            update_remote_metadata(bucket)
            process_cloud_inbox(bucket)
            handle_checkout_requests(bucket)
            cleanup_cloud_storage(bucket, limit_gb=5) # Soglia 5GB per anteprime
        except Exception as e:
            print(f"❌ Errore nel ciclo: {e}")
        
        time.sleep(30) # Controllo ogni 30 secondi
