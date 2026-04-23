import streamlit as st
import json
import time
import os
from google.cloud import storage

# --- CONFIGURAZIONE ---
st.set_page_config(page_title="Vault CAD Marco", layout="wide", page_icon="🏗️")

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

# --- CSS MINIMALISTA (Premium UI) ---
st.markdown("""
    <style>
    /* Rimuove i bordi e lo sfondo dai bottoni delle icone in colonna */
    div[data-testid="column"] button {
        border: none !important;
        background-color: transparent !important;
        padding: 0px !important;
        font-size: 24px !important;
        transition: transform 0.2s, color 0.2s;
        box-shadow: none !important;
    }
    /* Effetto ingrandimento al passaggio del mouse */
    div[data-testid="column"] button:hover {
        transform: scale(1.3);
        color: #0078D4 !important;
        background-color: transparent !important;
    }
    /* Stile specifico per il tasto + quando cliccato (attivo) */
    div[data-testid="column"] button:active {
        color: #28a745 !important;
        transform: scale(0.95);
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
        bucket = client.bucket("cad-vault-marco")
    except Exception as e:
        st.error(f"Errore connessione Cloud: {e}")
        st.stop()

    # --- FUNZIONI DIALOG ---
    @st.dialog("Dettaglio Tecnico", width="large")
    def preview_dialog(item):
        st.subheader(f"📦 {item['code']}")
        # Anteprima Immagine
        img_f = [f for f in item['formats'] if f.upper() in ['PNG', 'JPG', 'JPEG']]
        if img_f:
            cloud_p = f"archive/{item['code']}/{item['code']}.{img_f[0].lower()}"
            blob = bucket.blob(cloud_p)
            if blob.exists(): 
                st.image(blob.download_as_bytes())
            else: 
                st.info("📸 Anteprima in fase di sincronizzazione dal PC...")
                if st.button("🚀 Richiedi Sincronizzazione Ora"):
                    try:
                        q_blob = bucket.blob("metadata/sync_queue.json")
                        queue = json.loads(q_blob.download_as_text()) if q_blob.exists() else {}
                        queue[item['code']] = {"synced": False, "formats": item['formats'], "timestamp": time.time()}
                        q_blob.upload_from_string(json.dumps(queue))
                        st.success("Richiesta inviata!")
                    except: st.error("Errore invio richiesta.")
        
        st.divider()
        c1, c2 = st.columns(2)
        with c1: 
            st.write("**Tag:**")
            st.write(", ".join(item['tags']) if item['tags'] else "Nessuno")
        with c2: 
            st.write("**Formati (Download Singoli):**")
            for f in item['formats']:
                blob = bucket.blob(f"archive/{item['code']}/{item['code']}.{f.lower()}")
                if blob.exists():
                    st.download_button(f"⬇️ {f}", blob.download_as_bytes(), f"{item['code']}.{f.lower()}", key=f"dl_{f}")
                else: 
                    st.caption(f"⏳ {f} (Non sincronizzato)")

    # --- SIDEBAR ---
    with st.sidebar:
        st.title("⚙️ Sistema Vault")
        # Heartbeat
        try:
            hb_blob = bucket.blob("metadata/heartbeat.json")
            if hb_blob.exists():
                hb = json.loads(hb_blob.download_as_text())
                if (time.time() - hb['last_seen']) < 120: 
                    st.success("● ARCHIVIO ONLINE")
                else: st.error("● ARCHIVIO OFFLINE")
            else: st.warning("● STATO IGNOTO")
        except: st.warning("● ERRORE STATO")
        
        st.divider()
        st.subheader("⏳ In Sincronizzazione")
        try:
            q_blob = bucket.blob("metadata/sync_queue.json")
            if q_blob.exists():
                queue = json.loads(q_blob.download_as_text())
                if not queue: st.caption("Nessuna richiesta.")
                for code in queue: st.write(f"⏳ {code}...")
            else: st.caption("Coda non trovata.")
        except: st.caption("Errore lettura coda.")

        st.divider()
        st.subheader("🕒 Recenti (Scadenza 24h)")
        try:
            h_blob = bucket.blob("metadata/history.json")
            if h_blob.exists():
                hist = json.loads(h_blob.download_as_text())
                if not hist: st.caption("Nessuna cronologia.")
                for entry in hist:
                    elapsed = time.time() - entry['timestamp_sync']
                    rem = 24 - int(elapsed / 3600)
                    if rem > 0:
                        if st.button(f"📦 {entry['code']} ({rem}h rimaste)", key=f"hist_{entry['code']}", use_container_width=True):
                            st.session_state.f1_query = entry['code']
                            st.rerun()
                    else:
                        st.caption(f"📦 {entry['code']} (In scadenza...)")
            else: st.caption("Nessuna cronologia.")
        except: st.caption("Errore lettura cronologia.")

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
                    st.toast("Check-in in corso...")
            else:
                st.error("Inserisci il codice articolo e almeno un file!")

    with t2:
        st.subheader("Ricerca nell'Archivio")
        # Carica l'indice dal cloud
        try:
            idx_blob = bucket.blob("metadata/archivio_index.json")
            if idx_blob.exists():
                index_data = json.loads(idx_blob.download_as_text()).get("components", [])
            else:
                st.warning("Indice archivio non trovato. Il Bridge deve ancora sincronizzarlo.")
                index_data = []
        except:
            st.error("Errore caricamento indice.")
            index_data = []

        c1, c2 = st.columns(2)
        with c1: 
            n1 = st.text_input("Ricerca Codice", value=st.session_state.f1_query, key="f1").lower()
            st.session_state.f1_query = ""
        with c2: n2 = st.text_input("Filtro Categoria/Altro", key="f2").lower()
        
        filtered = [item for item in index_data if (n1 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower() and n2 in (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower())]
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
                            try:
                                q_blob = bucket.blob("metadata/sync_queue.json")
                                queue = json.loads(q_blob.download_as_text()) if q_blob.exists() else {}
                                queue[item['code']] = {"synced": False, "formats": item['formats'], "timestamp": time.time()}
                                q_blob.upload_from_string(json.dumps(queue))
                                st.toast(f"Richiesta sync inviata per {item['code']}")
                            except: st.error("Errore invio sync.")

        if len(filtered) > st.session_state.limit_results:
            st.button("Mostra altri risultati...", on_click=show_more)
