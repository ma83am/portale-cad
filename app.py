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

# --- CSS REFINEMENT (Version 4.1) ---
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
    div[data-testid="column"] button:hover { 
        transform: scale(1.3); 
        color: #0078D4 !important; 
        background-color: transparent !important;
    }
    div[data-testid="column"] button:active {
        color: #28a745 !important;
        transform: scale(0.95);
    }
    /* Pulsanti download singoli nel Dialog */
    .stDownloadButton button { 
        border: 1px solid #ddd !important; 
        background-color: #f9f9f9 !important; 
        font-size: 14px !important; 
        padding: 5px 15px !important; 
        border-radius: 5px !important;
    }
    .stCheckbox { margin-top: 10px; }
    .stAlert { border-radius: 10px; }
    label, p, h1, h2, h3 { color: #212529 !important; font-family: 'Segoe UI', sans-serif; }
    </style>
    """, unsafe_allow_html=True)

# Inizializzazione Sessione
if "download_queue" not in st.session_state: 
    st.session_state.download_queue = set()
if "f1_query" not in st.session_state:
    st.session_state.f1_query = ""
if "limit_results" not in st.session_state:
    st.session_state.limit_results = 25
if "password_correct" not in st.session_state:
    st.session_state["password_correct"] = False

def show_more():
    st.session_state.limit_results += 25

def check_password():
    if not st.session_state["password_correct"]:
        st.title("🔒 Accesso Riservato")
        pwd = st.text_input("Inserisci la password", type="password")
        if st.button("Accedi"):
            if pwd == st.secrets["login"]["password"]:
                st.session_state["password_correct"] = True
                st.rerun()
            else: st.error("Password errata")
        return False
    return True

# --- CONNESSIONE CLOUD ---
if check_password():
    try:
        gcp_info = json.loads(st.secrets["gcp_service_account"])
        client = storage.Client.from_service_account_info(gcp_info)
        bucket = client.bucket(BUCKET_NAME)
    except Exception as e:
        st.error(f"Errore connessione Cloud: {e}")
        st.stop()

    # --- HELPER FUNCTIONS ---
    def get_cloud_json(path):
        try:
            blob = bucket.blob(path)
            return json.loads(blob.download_as_text()) if blob.exists() else {}
        except: return {}

    def save_cloud_json(path, data):
        bucket.blob(path).upload_from_string(json.dumps(data))

    def add_to_sync(code, fmts):
        queue = get_cloud_json("metadata/sync_queue.json")
        if code not in queue: queue[code] = {"formats": [], "synced": False}
        for f in fmts:
            if f not in queue[code]["formats"]:
                queue[code]["formats"].append(f)
        save_cloud_json("metadata/sync_queue.json", queue)
        st.toast(f"Richiesta inviata al PC per {code}!")

    # --- DIALOG ANTEPRIMA (Version 4.1) ---
    @st.dialog("Dettaglio Tecnico", width="large")
    def preview_dialog(item):
        st.subheader(f"📦 {item['code']}")
        # Anteprima Immagine
        img_f = [f for f in item['formats'] if f.upper() in ['PNG', 'JPG', 'JPEG']]
        if img_f:
            cloud_p = f"archive/{item['code']}/{item['code']}.{img_f[0].lower()}"
            blob = bucket.blob(cloud_p)
            if blob.exists(): 
                st.image(blob.download_as_bytes(), caption="Anteprima Grafica")
            else: 
                st.info("📸 Anteprima in fase di sincronizzazione dal PC...")
        
        st.divider()
        st.write("**Formati (Download Singoli):**")
        queue = get_cloud_json("metadata/sync_queue.json")
        
        for fmt in item['formats']:
            ext = fmt.lower()
            blob = bucket.blob(f"archive/{item['code']}/{item['code']}.{ext}")
            c_btn, c_spacer = st.columns([1, 4])
            with c_btn:
                if blob.exists():
                    st.download_button(label=f"⬇️ {fmt}", data=blob.download_as_bytes(), 
                                     file_name=f"{item['code']}.{ext}", key=f"dl_{item['code']}_{fmt}")
                elif item['code'] in queue and fmt in queue[item['code']]['formats']:
                    st.button(f"⏳ {fmt}", key=f"wait_{item['code']}_{fmt}", disabled=True, help="In coda...")
                else:
                    if st.button(f"⏳ {fmt}", key=f"req_{item['code']}_{fmt}", help="Richiedi Sincronizzazione"):
                        add_to_sync(item['code'], [fmt])
                        st.rerun()

        st.divider()
        st.write(f"**Tag:** {', '.join(item['tags']) if item['tags'] else 'Nessuno'}")
        st.caption(f"Percorso Archivio: {item.get('category', 'N/D')}")

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("⚙️ Sistema Vault")
        # Heartbeat
        hb = get_cloud_json("metadata/heartbeat.json")
        if (time.time() - hb.get('last_seen', 0)) < 120: st.success("● ARCHIVIO ONLINE")
        else: st.error("● ARCHIVIO OFFLINE")
        
        st.divider()
        st.subheader("⏳ In Sincronizzazione")
        queue = get_cloud_json("metadata/sync_queue.json")
        if not queue: st.caption("Coda vuota.")
        for code in queue: st.write(f"⏳ {code}...")

        st.divider()
        st.subheader("🕒 Recenti (Scadenza 24h)")
        history = get_cloud_json("metadata/history.json")
        if not history: st.caption("Nessun file sincronizzato.")
        for entry in history:
            elapsed = time.time() - entry['timestamp_sync']
            rem = 24 - int(elapsed / 3600)
            if rem > 0:
                with st.expander(f"📦 {entry['code']} ({rem}h rimaste)"):
                    for f in entry.get('formats', []):
                        b = bucket.blob(f"archive/{entry['code']}/{entry['code']}.{f.lower()}")
                        if b.exists():
                            st.download_button(f"Scarica {f}", b.download_as_bytes(), 
                                             f"{entry['code']}.{f.lower()}", key=f"hdl_{entry['code']}_{f}")
                        else: st.caption(f"⏳ {f}")
            else: st.caption(f"📦 {entry['code']} (Scaduto)")

    # --- CORPO CENTRALE ---
    st.image("cover.jpg", use_container_width=True)
    st.title("🏗️ Vault CAD Centrale")
    t1, t2 = st.tabs(["📤 CHECK-IN", "🔍 CHECK-OUT"])

    with t1:
        st.subheader("Nuovo Inserimento")
        col1, col2 = st.columns(2)
        with col1: nome_art = st.text_input("Codice Articolo", placeholder="es. GUIDA_PALLET")
        with col2: tags_art = st.text_input("Tag (separati da virgola)")
        
        sel_cat = st.selectbox("Seleziona Categoria", list(CATEGORIE_FISSE.keys()))
        path_rel = CATEGORIE_FISSE[sel_cat]
        st.info(f"📍 Destinazione: D:/ARCHIVIO CAD/{path_rel}/{nome_art if nome_art else '...'}/")
        
        files = st.file_uploader("Trascina i file dell'articolo", accept_multiple_files=True)
        if st.button("🚀 ESEGUI CHECK-IN", use_container_width=True, type="primary"):
            if nome_art and files:
                with st.spinner("Invio al Cloud..."):
                    task = {"nome_articolo": nome_art, "percorso_relativo": path_rel, "tags": [t.strip() for t in tags_art.split(',')], "solo_trasferimento": False}
                    prefix = f"inbox/{nome_art}_{int(time.time())}"
                    bucket.blob(f"{prefix}/{nome_art}_task.json").upload_from_string(json.dumps(task))
                    for f in files:
                        bucket.blob(f"{prefix}/{f.name}").upload_from_string(f.getvalue())
                    st.success("Richiesta inviata al Bridge locale!")
            else: st.error("Dati incompleti.")

    with t2:
        st.subheader("Ricerca nell'Archivio")
        # Carica l'indice dal cloud
        idx_data = get_cloud_json("metadata/archivio_index.json").get("components", [])
        if not idx_data: st.warning("Indice in fase di caricamento...")

        c1, c2 = st.columns(2)
        with c1: 
            n1 = st.text_input("Ricerca Codice", value=st.session_state.f1_query, key="f1").lower()
            st.session_state.f1_query = ""
        with c2: n2 = st.text_input("Filtro Categoria/Altro", key="f2").lower()
        
        filtered = [item for item in idx_data if (n1 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower() and n2 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower())]
        st.info(f"📍 Risultati: {len(filtered)}")

        with st.container(height=550, border=False):
            for item in filtered[:st.session_state.limit_results]:
                with st.container(border=True):
                    c_txt, c_view, c_add = st.columns([0.8, 0.1, 0.1])
                    with c_txt: 
                        st.markdown(f"**{item['code']}**")
                        st.caption(f"{item['category']} | {', '.join(item['formats'])}")
                    with c_view: 
                        if st.button("🔍", key=f"v_{item['code']}", help="Dettagli e Download Singoli"):
                            preview_dialog(item)
                    with c_add:
                        if st.button("➕", key=f"a_{item['code']}", help="Richiedi Sincronizzazione Cloud"):
                            add_to_sync(item['code'], item['formats'])

        if len(filtered) > st.session_state.limit_results:
            st.button("Mostra altri risultati...", on_click=show_more)
