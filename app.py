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
st.set_page_config(page_title="Vault CAD Marco", layout="wide", page_icon="🏗️")

# --- CSS REFINEMENT (Version 4.4) ---
st.markdown("""
    <style>
    /* Icone minimali per i bottoni in colonna */
    div[data-testid="column"] button { 
        border: none !important; 
        background-color: transparent !important; 
        font-size: 24px !important; 
        padding: 0px !important; 
        transition: transform 0.2s, color 0.2s;
        box-shadow: none !important;
    }
    div[data-testid="column"] button:hover { transform: scale(1.3); color: #0078D4 !important; }
    
    /* Pulsanti Sidebar e Bulk */
    .stButton > button { width: 100%; border-radius: 5px; }
    .stDownloadButton button { border: 1px solid #ddd !important; background-color: #f9f9f9 !important; font-size: 14px !important; border-radius: 5px !important; }
    
    label, p, h1, h2, h3 { color: #212529 !important; font-family: 'Segoe UI', sans-serif; }
    .stAlert { border-radius: 10px; }
    </style>
    """, unsafe_allow_html=True)

# --- 2. GESTIONE SESSIONE (F5 PERSISTENCE & 2H TIMER) ---
def check_password():
    params = st.query_params
    if params.get("auth") == "true":
        try:
            login_time = float(params.get("t", 0))
            if (time.time() - login_time) < 7200: return True
            else:
                st.query_params.clear()
                st.warning("Sessione scaduta (2 ore).")
        except: st.query_params.clear()

    st.title("🔒 Accesso Riservato Vault")
    pwd = st.text_input("Password di sistema", type="password")
    if st.button("Accedi"):
        if pwd == st.secrets["login"]["password"]:
            st.query_params["auth"] = "true"
            st.query_params["t"] = str(time.time())
            st.rerun()
        else: st.error("Password errata.")
    return False

def logout():
    st.query_params.clear()
    st.rerun()

# --- LOGICA DI STATO ---
if "bulk_list" not in st.session_state: st.session_state.bulk_list = []
if "limit_results" not in st.session_state: st.session_state.limit_results = 25
if "f1_query" not in st.session_state: st.session_state.f1_query = ""

def show_more(): st.session_state.limit_results += 25

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

    def add_task_to_sync(code, task_type="item_zip", items=None):
        queue = get_cloud_json("metadata/sync_queue.json")
        task_id = f"{task_type}_{int(time.time())}"
        queue[task_id] = {
            "code": code,
            "type": task_type, # 'item_zip', 'bulk_zip', 'link'
            "items": items if items else [code],
            "synced": False,
            "timestamp": time.time()
        }
        bucket.blob("metadata/sync_queue.json").upload_from_string(json.dumps(queue))
        st.toast(f"Richiesta {task_type} inviata!")

    # --- 3. SIDEBAR (Design 4.4 con Box Bordati) ---
    with st.sidebar:
        st.title("⚙️ Sistema Vault")
        hb = get_cloud_json("metadata/heartbeat.json")
        if (time.time() - hb.get('last_seen', 0)) < 120: st.success("● ARCHIVIO ONLINE")
        else: st.error("● ARCHIVIO OFFLINE")
        
        if st.button("🚪 Esci dal sistema", help="Disconnetti"): logout()
        st.divider()
        
        st.subheader("⏳ In Sincronizzazione")
        queue = get_cloud_json("metadata/sync_queue.json")
        if not queue: st.caption("Coda vuota.")
        for tid, data in queue.items(): st.write(f"⏳ {data.get('code', tid)}")

        st.divider()
        st.subheader("🕒 Recenti (Scadenza 24h)")
        history = get_cloud_json("metadata/history.json")
        if not history: st.caption("Nessun file pronto.")
        else:
            for entry in list(history)[:15]:
                with st.container(border=True):
                    st.write(f"📦 **{entry['code']}**")
                    if entry.get('type') == 'link':
                        url = entry.get('url', '')
                        st.code(url, language=None)
                        st.caption("🔗 Link valido per 24 ore")
                    else:
                        zip_blob = bucket.blob(f"archive/{entry['code']}/{entry['code']}.zip")
                        if zip_blob.exists():
                            st.download_button(
                                label="⬇️ Scarica ZIP",
                                data=zip_blob.download_as_bytes(),
                                file_name=f"{entry['code']}.zip",
                                key=f"dl_zip_{entry['code']}"
                            )
                        else:
                            # Se non è uno ZIP, mostra i formati singoli
                            for f in entry.get('formats', []):
                                b = bucket.blob(f"archive/{entry['code']}/{entry['code']}.{f.lower()}")
                                if b.exists():
                                    st.download_button(f"⬇️ {f}", b.download_as_bytes(), f"{entry['code']}.{f.lower()}", key=f"hdl_{entry['code']}_{f}")

    # --- 4. CORPO CENTRALE ---
    st.image("cover.jpg", use_container_width=True)
    st.title("🏗️ Vault CAD Centrale")
    t1, t2 = st.tabs(["📤 CHECK-IN", "🔍 CHECK-OUT"])

    @st.dialog("Dettaglio Tecnico", width="large")
    def preview_dialog(item):
        st.subheader(f"📦 {item['code']}")
        img_f = [f for f in item['formats'] if f.upper() in ['PNG', 'JPG', 'JPEG']]
        if img_f:
            img_b = bucket.blob(f"archive/{item['code']}/{item['code']}.{img_f[0].lower()}")
            if img_b.exists(): st.image(img_b.download_as_bytes())
        st.divider()
        c_t, c_f = st.columns(2)
        with c_t: st.write("**🏷️ Tag:**"); st.write(", ".join(item.get('tags', [])) if item.get('tags') else "Nessuno")
        with c_f:
            st.write("**📂 Download Singoli:**")
            q = get_cloud_json("metadata/sync_queue.json")
            for fmt in item['formats']:
                ext = fmt.lower(); b = bucket.blob(f"archive/{item['code']}/{item['code']}.{ext}")
                cb, cs = st.columns([1, 4])
                with cb:
                    if b.exists(): st.download_button(f"⬇️ {fmt}", b.download_as_bytes(), f"{item['code']}.{ext}", key=f"pdl_{item['code']}_{fmt}")
                    else: st.button(f"⏳ {fmt}", key=f"pw_{item['code']}_{fmt}", disabled=True)

    with t1:
        st.subheader("Nuovo Inserimento")
        c1, c2 = st.columns(2)
        with c1: n_art = st.text_input("Codice Articolo", placeholder="es. MOTORE_ABB")
        with c2: t_art = st.text_input("Tag (separati da virgola)")
        sel_cat = st.selectbox("Categoria", list(CATEGORIE_FISSE.keys()))
        files = st.file_uploader("Trascina file", accept_multiple_files=True)
        if st.button("🚀 ESEGUI CHECK-IN", use_container_width=True, type="primary") and n_art and files:
            task = {"nome_articolo": n_art, "percorso_relativo": CATEGORIE_FISSE[sel_cat], "tags": [t.strip() for t in t_art.split(',')], "solo_trasferimento": False}
            prefix = f"inbox/{n_art}_{int(time.time())}"
            bucket.blob(f"{prefix}/{n_art}_task.json").upload_from_string(json.dumps(task))
            for f in files: bucket.blob(f"{prefix}/{f.name}").upload_from_string(f.getvalue())
            st.success("Archiviazione inviata al Bridge!")

    with t2:
        st.subheader("Ricerca nell'Archivio")
        idx = get_cloud_json("metadata/archivio_index.json").get("components", [])
        c1, c2 = st.columns(2)
        with c1: n1 = st.text_input("Codice 1", value=st.session_state.f1_query, key="f1").lower(); st.session_state.f1_query = ""
        with c2: n2 = st.text_input("Codice 2", key="f2").lower()
        t1, t2, t3 = st.columns(3)
        with t1: tag1 = t1.text_input("Tag 1", key="t1").lower()
        with t2: tag2 = t2.text_input("Tag 2", key="t2").lower()
        with t3: tag3 = t3.text_input("Tag 3", key="t3").lower()

        filtered = [i for i in idx if (n1 in i['code'].lower() and n2 in i['code'].lower()) and (tag1 in " ".join(i.get('tags', [])).lower() and tag2 in " ".join(i.get('tags', [])).lower() and tag3 in " ".join(i.get('tags', [])).lower())]
        st.info(f"📍 Risultati: {len(filtered)}")

        with st.container(height=500, border=False):
            for item in filtered[:st.session_state.limit_results]:
                with st.container(border=True):
                    ctx, cv, cz, ca = st.columns([0.7, 0.1, 0.1, 0.1])
                    with ctx: st.markdown(f"**{item['code']}**"); st.caption(f"{item['category']} | {', '.join(item['formats'])}")
                    with cv: 
                        if st.button("🔍", key=f"v_{item['code']}", help="Dettagli e singoli"): preview_dialog(item)
                    with cz:
                        if st.button("📦", key=f"z_{item['code']}", help="Prepara ZIP articolo"): add_task_to_sync(item['code'], "item_zip")
                    with ca:
                        is_in = item['code'] in st.session_state.bulk_list
                        if st.button("✅" if is_in else "➕", key=f"a_{item['code']}", help="Aggiungi al Carrello"):
                            if is_in: st.session_state.bulk_list.remove(item['code'])
                            else: st.session_state.bulk_list.append(item['code'])
                            st.rerun()
        if len(filtered) > st.session_state.limit_results: st.button("Mostra altri...", on_click=show_more)

        # --- ZONA CARRELLO (Design 4.4) ---
        if st.session_state.bulk_list:
            st.markdown("---")
            st.subheader("🧺 Carrello Spedizione Bulk")
            st.info(f"Articoli selezionati: **{', '.join(st.session_state.bulk_list)}**")
            c1, c2, c3 = st.columns(3)
            with c1:
                if st.button("🚀 PREPARA ZIP", use_container_width=True):
                    add_task_to_sync(f"BULK_{int(time.time())}", "bulk_zip", st.session_state.bulk_list)
                    st.session_state.bulk_list = []; st.rerun()
            with c2:
                if st.button("🔗 GENERA LINK", use_container_width=True):
                    add_task_to_sync(f"LINK_{int(time.time())}", "link", st.session_state.bulk_list)
                    st.session_state.bulk_list = []; st.rerun()
            with c3:
                if st.button("🗑️ Svuota Carrello", use_container_width=True):
                    st.session_state.bulk_list = []; st.rerun()
