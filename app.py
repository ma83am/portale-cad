import streamlit as st
import json
import time
import os
from google.cloud import storage

# --- 1. DEFINIZIONE RIGIDA CATEGORIE ---
CATEGORIE_FISSE = {
    "1_ASSIEMI": "1_ASSIEMI",
    "2_GRUPPI": "2_GRUPPI",
    "3_COMPONENTI A DISEGNO": "3_COMPONENTI A DISEGNO",
    "4_COMMERCIALI": "4_COMMERCIALI",
    "4.1_A CATALOGO": "4_COMMERCIALI/4.1_A CATALOGO",
    "4.2_COMMERCIALI_LAVORATI": "4_COMMERCIALI/4.2_COMMERCIALI_LAVORATI",
    "4.3_GENERICI": "4_COMMERCIALI/4.3_GENERICI",
    "8_CATALOGHI": "8_CATALOGHI",
    "9_NON CLASSIFICATI": "9_NON CLASSIFICATI"
}

# --- CONFIGURAZIONE CORE ---
BUCKET_NAME = "cad-vault-marco"
LIMIT_TOTAL_GB = 4.5
LIMIT_IMAGES_MB = 500.0
UPLOAD_PREFIX = "portale_inbox" # CAMBIATO PER EVITARE CONFLITTI

st.set_page_config(page_title="Vault CAD Marco", layout="wide", page_icon="🏗️")

# --- CSS REFINEMENT ---
st.markdown("""
    <style>
    div[data-testid="column"] button { border: none !important; background-color: transparent !important; font-size: 24px !important; padding: 0px !important; }
    .stButton > button { width: 100%; border-radius: 5px; font-size: 14px !important; }
    .stDownloadButton button { border: 1px solid #ddd !important; background-color: #f9f9f9 !important; font-size: 14px !important; border-radius: 5px !important; }
    label, p, h1, h2, h3 { color: #212529 !important; font-family: 'Segoe UI', sans-serif; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. GESTIONE SESSIONE ---
def check_password():
    params = st.query_params
    if params.get("auth") == "true":
        try:
            login_time = float(params.get("t", 0))
            if (time.time() - login_time) < 7200: return True
            else: st.query_params.clear(); st.warning("Sessione scaduta.")
        except: st.query_params.clear()
    st.title("🔒 Accesso Riservato Vault")
    pwd = st.text_input("Password", type="password")
    if st.button("Accedi"):
        if pwd == st.secrets["login"]["password"]:
            st.query_params["auth"] = "true"; st.query_params["t"] = str(time.time()); st.rerun()
        else: st.error("Errore.")
    return False

# --- STATO ---
if "bulk_list" not in st.session_state: st.session_state.bulk_list = []
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0

# --- ESECUZIONE ---
if check_password():
    gcp_info = json.loads(st.secrets["gcp_service_account"])
    client = storage.Client.from_service_account_info(gcp_info)
    bucket = client.bucket(BUCKET_NAME)

    def get_cloud_json(path):
        try:
            blob = bucket.blob(path)
            return json.loads(blob.download_as_text()) if blob.exists() else {}
        except: return {}

    @st.cache_data(ttl=300)
    def get_bucket_metrics():
        blobs = list(bucket.list_blobs())
        t_b = sum(b.size for b in blobs); i_b = sum(b.size for b in blobs if b.name.lower().endswith(('.png', '.jpg', '.jpeg')))
        return t_b / (1024**3), i_b / (1024**2)

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("⚙️ Sistema Vault")
        hb = get_cloud_json("metadata/heartbeat.json")
        if (time.time() - hb.get('last_seen', 0)) < 120: st.success("● ONLINE")
        else: st.error("● OFFLINE")
        if st.button("🚪 Logout"): st.query_params.clear(); st.rerun()
        
        st.write("---")
        total_gb, img_mb = get_bucket_metrics()
        st.write(f"📊 Cloud: {total_gb:.2f} GB / {LIMIT_TOTAL_GB} GB")
        st.progress(min(total_gb / LIMIT_TOTAL_GB, 1.0))
        
        st.divider()
        st.subheader("🕒 Recenti")
        history = get_cloud_json("metadata/history.json")
        for entry in list(history)[:10]:
            with st.container(border=True):
                st.write(f"📦 **{entry['code']}**")
                if entry.get('type') == 'link': st.code(entry.get('url', ''), language=None)
                else:
                    b = bucket.blob(f"archive/{entry['code']}/{entry['code']}.zip")
                    if b.exists(): st.download_button("⬇️ ZIP", b.download_as_bytes(), f"{entry['code']}.zip", key=f"dl_{entry['code']}")

    # --- TAB ---
    t1, t2 = st.tabs(["📤 CHECK-IN", "🔍 CHECK-OUT"])

    with t1:
        st.subheader("Archiviazione (Semi-Auto)")
        c1, c2 = st.columns(2)
        with c1: n_art = st.text_input("Codice Articolo")
        with c2: t_art = st.text_input("Tag")
        sel_cat = st.selectbox("Categoria", list(CATEGORIE_FISSE.keys()))
        files = st.file_uploader("Trascina file", accept_multiple_files=True, key=f"up_{st.session_state.uploader_key}")
        
        if st.button("🚀 INVIA AL BRIDGE", use_container_width=True, type="primary") and n_art and files:
            with st.spinner("Invio..."):
                task = {"nome_articolo": n_art, "percorso_relativo": CATEGORIE_FISSE[sel_cat], "tags": [t.strip() for t in t_art.split(',')], "solo_trasferimento": True}
                ts = int(time.time())
                prefix = f"{UPLOAD_PREFIX}/{n_art}_{ts}"
                bucket.blob(f"{prefix}/{n_art}_task.json").upload_from_string(json.dumps(task))
                for f in files: bucket.blob(f"{prefix}/{f.name}").upload_from_string(f.getvalue())
                st.session_state.uploader_key += 1
                st.success("Inviato!")
                time.sleep(1); st.rerun()

    with t2:
        st.subheader("Ricerca")
        idx = get_cloud_json("metadata/archivio_index.json").get("components", [])
        q = st.text_input("Cerca Codice").lower()
        filtered = [i for i in idx if q in i['code'].lower()]
        for item in filtered[:25]:
            with st.container(border=True):
                c_n, c_z, c_a = st.columns([0.8, 0.1, 0.1])
                with c_n: st.write(f"**{item['code']}**"); st.caption(item['category'])
                with c_z: 
                    if st.button("📦", key=f"z_{item['code']}"):
                        q_data = get_cloud_json("metadata/sync_queue.json")
                        tid = f"zip_{int(time.time())}"
                        q_data[tid] = {"code": item['code'], "type": "item_zip", "items": [item['code']], "synced": False}
                        bucket.blob("metadata/sync_queue.json").upload_from_string(json.dumps(q_data))
                        st.toast("Richiesta ZIP inviata.")
                with c_a:
                    if st.button("➕", key=f"a_{item['code']}"):
                        st.session_state.bulk_list.append(item['code']); st.rerun()
        
        if st.session_state.bulk_list:
            st.divider(); st.write(f"Carrello: {', '.join(st.session_state.bulk_list)}")
            if st.button("🚀 GENERA ZIP BULK"):
                q_data = get_cloud_json("metadata/sync_queue.json")
                tid = f"bulk_{int(time.time())}"
                q_data[tid] = {"code": f"BULK_{int(time.time())}", "type": "bulk_zip", "items": st.session_state.bulk_list, "synced": False}
                bucket.blob("metadata/sync_queue.json").upload_from_string(json.dumps(q_data))
                st.session_state.bulk_list = []; st.rerun()
