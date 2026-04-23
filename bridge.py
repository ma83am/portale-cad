import os
import time
import json
import shutil
from google.cloud import storage

# --- CONFIGURAZIONE ---
os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = r"secrets\key.json"
BASE_PATH = r"D:\ARCHIVIO CAD"
BUCKET_NAME = "cad-vault-marco"
INBOX_ROOT = os.path.join(BASE_PATH, "0_FILE DA PROCESSARE")
CLOUD_INBOX = os.path.join(INBOX_ROOT, "CLOUD_INBOX")

client = storage.Client()
bucket = client.bucket(BUCKET_NAME)

def run_bridge():
    print(f"🚀 Bridge 4.2 Operativo (F5 Persistence Support & 24h Clean)")
    while True:
        try:
            # 1. Heartbeat & Index Sync (Necessario per l'App web)
            bucket.blob("metadata/heartbeat.json").upload_from_string(json.dumps({"last_seen": time.time()}))
            idx_local = os.path.join(BASE_PATH, "archivio.json")
            if os.path.exists(idx_local):
                bucket.blob("metadata/archivio_index.json").upload_from_filename(idx_local)

            # 2. Gestione Sincronizzazione Urgente (Coda)
            q_blob = bucket.blob("metadata/sync_queue.json")
            if q_blob.exists():
                queue = json.loads(q_blob.download_as_text())
                h_blob = bucket.blob("metadata/history.json")
                history = json.loads(h_blob.download_as_text()) if h_blob.exists() else []
                with open(idx_local, 'r') as f:
                    db = json.load(f).get('components', [])
                updated = False
                for code, data in list(queue.items()):
                    item = next((i for i in db if i['code'] == code), None)
                    if item:
                        folder = os.path.dirname(item['path'])
                        synced_fmts = []
                        for fmt in data.get('formats', []):
                            local_f = os.path.join(folder, f"{code}.{fmt.lower()}")
                            if os.path.exists(local_f):
                                bucket.blob(f"archive/{code}/{code}.{fmt.lower()}").upload_from_filename(local_f)
                                synced_fmts.append(fmt)
                                print(f"⚡ Sync OK: {code}.{fmt}")
                        
                        del queue[code]
                        # Aggiorna history (evita duplicati)
                        history = [h for h in history if h['code'] != code]
                        history.insert(0, {
                            "code": code, 
                            "formats": synced_fmts if synced_fmts else data.get('formats', []), 
                            "timestamp_sync": time.time(),
                            "category": item['category']
                        })
                        updated = True
                if updated:
                    q_blob.upload_from_string(json.dumps(queue))
                    h_blob.upload_from_string(json.dumps(history[:20]))

            # 3. Gestione Check-in
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
                    
                    prefix = t_blob.name.replace('_task.json', '')
                    fmts = []
                    main_path = ""
                    for b in blobs:
                        if b.name.startswith(prefix) and not b.name.endswith('_task.json'):
                            orig_ext = b.name.split('.')[-1].lower()
                            local_f_path = os.path.join(dest_dir, f"{nome}.{orig_ext}")
                            b.download_to_filename(local_f_path)
                            fmts.append(orig_ext.upper())
                            if orig_ext.upper() in ['STP', 'STEP', 'IAM', 'ASM', 'DWG', 'SLDPRT']:
                                main_path = local_f_path
                            b.delete()
                    
                    if not data.get('solo_trasferimento'):
                        with open(idx_local, 'r+') as f:
                            db_loc = json.load(f)
                            db_loc['components'] = [c for c in db_loc.get('components', []) if c['code'] != nome]
                            db_loc['components'].append({
                                "code": nome, "category": data['percorso_relativo'], "tags": data['tags'],
                                "formats": list(set(fmts)), 
                                "path": main_path if main_path else os.path.join(dest_dir, f"{nome}.{fmts[0].lower()}"),
                                "last_update": time.strftime("%Y-%m-%d %H:%M:%S")
                            })
                            f.seek(0); json.dump(db_loc, f, indent=4); f.truncate()
                    
                    t_blob.delete()
                    print(f"📥 Archiviato: {nome}")
                except Exception as e: print(f"❌ Errore Check-in {t_blob.name}: {e}")

            # 4. Cleanup 24h
            h_blob = bucket.blob("metadata/history.json")
            if h_blob.exists():
                try:
                    hist = json.loads(h_blob.download_as_text())
                    new_hist = []
                    changed_h = False
                    for entry in hist:
                        if (time.time() - entry['timestamp_sync']) < 86400:
                            new_hist.append(entry)
                        else:
                            blobs_del = bucket.list_blobs(prefix=f"archive/{entry['code']}/")
                            for bd in blobs_del: bd.delete()
                            changed_h = True
                            print(f"🗑️ Scaduto: {entry['code']}")
                    if changed_h: h_blob.upload_from_string(json.dumps(new_hist))
                except Exception as e: print(f"❌ Errore Cleanup: {e}")

        except Exception as e: print(f"⚠️ Errore Ciclo: {e}")
        time.sleep(15)

if __name__ == "__main__":
    import sys, io
    if sys.platform == "win32":
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    run_bridge()
