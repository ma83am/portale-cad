import streamlit as st
import os
import json
import time
from google.cloud import storage

# --- CONFIGURAZIONE CORE ---
BUCKET_NAME = "cad-vault-marco"

st.set_page_config(page_title="PORTALE CAD", layout="wide", page_icon="🏗️")

# --- LOGICA DI STATO (Inizializzazione) ---
if "limit_results" not in st.session_state:
    st.session_state.limit_results = 25
if "download_queue" not in st.session_state:
    st.session_state.download_queue = set()
if "f1_query" not in st.session_state:
    st.session_state.f1_query = ""

def show_more():
    st.session_state.limit_results += 25

# --- 1. FUNZIONE CONTROLLO STATO SERVER (Heartbeat) ---
def get_server_status(bucket):
    """Verifica se il Bridge locale è attivo leggendo il segnale di vita."""
    try:
        blob = bucket.blob("metadata/heartbeat.json")
        data = json.loads(blob.download_as_text())
        last_seen = data.get("last_seen", 0)
        
        if (time.time() - last_seen) < 120:
            return "🟢 SERVER ONLINE (PC H24)"
        else:
            return "🔴 SERVER OFFLINE (PC Spento)"
    except:
        return "⚪ STATO SCONOSCIUTO"

# --- 2. FUNZIONE PERSISTENZA SIDEBAR (Sync & History) ---
def get_sync_data(bucket):
    """Recupera la coda di sincronizzazione e lo storico dei componenti dal Cloud."""
    try:
        q_blob = bucket.blob("metadata/sync_queue.json")
        h_blob = bucket.blob("metadata/history.json")
        
        queue = json.loads(q_blob.download_as_text()) if q_blob.exists() else {}
        history = json.loads(h_blob.download_as_text()) if h_blob.exists() else []
        return queue, history
    except:
        return {}, []

# --- FUNZIONE DI SICUREZZA ---
def check_password():
    """Restituisce True se l'utente ha inserito la password corretta tramite Secrets."""
    if "password_correct" not in st.session_state:
        st.session_state["password_correct"] = False

    if not st.session_state["password_correct"]:
        st.title("🔒 Accesso Riservato")
        pwd = st.text_input("Inserisci la password dell'Archivio", type="password")
        if st.button("Accedi"):
            try:
                if pwd == st.secrets["login"]["password"]:
                    st.session_state["password_correct"] = True
                    st.rerun()
                else:
                    st.error("Password errata")
            except KeyError:
                st.error("Errore di configurazione: 'login/password' non trovato nei Secrets.")
        return False
    return True

# --- 3. DIALOG PER ANTEPRIMA (Versione Ingrandita) ---
@st.dialog("Anteprima Tecnica Articolo", width="large")
def preview_dialog(item, bucket):
    st.write(f"🔍 **Dettaglio Codice:** {item['code']}")
    img_formats = [f for f in item.get('formats', []) if f.upper() in ['JPG', 'PNG', 'JPEG']]
    
    if img_formats:
        ext = img_formats[0].lower()
        cloud_path = f"archive/{item['code']}/{item['code']}.{ext}"
        try:
            blob = bucket.blob(cloud_path)
            img_bytes = blob.download_as_bytes()
            st.image(img_bytes, caption=f"Anteprima di {item['code']}")
            st.download_button("💾 Scarica questa immagine", img_bytes, file_name=f"{item['code']}.jpg")
        except:
            st.error("L'immagine è registrata ma non ancora caricata nel Cloud dal Bridge locale.")
            # Se l'utente clicca qui, aggiungiamo alla coda urgente
            if st.button("🚀 Richiedi Sincronizzazione Urgente"):
                q, h = get_sync_data(bucket)
                q[item['code']] = {"synced": False, "formats": img_formats, "timestamp": time.time()}
                bucket.blob("metadata/sync_queue.json").upload_from_string(json.dumps(q))
                st.success("Richiesta inviata al Bridge locale!")
                st.rerun()
    else:
        st.warning("Nessuna anteprima disponibile.")
    st.divider()
    st.json({"Tag": item.get('tags', []), "Formati": item.get('formats', [])})

# --- LOGICA ESECUZIONE ---
if check_password():
    # Inizializzazione Google Cloud dai Secrets
    try:
        gcp_info = json.loads(st.secrets["gcp_service_account"])
        client = storage.Client.from_service_account_info(gcp_info)
        bucket = client.bucket(BUCKET_NAME)
    except Exception as e:
        st.error(f"Errore connessione Cloud: {e}")
        st.stop()

    # --- SIDEBAR DASHBOARD ---
    queue, history = get_sync_data(bucket)
    
    with st.sidebar:
        # Immagine copertina ridotta in sidebar o logo (opzionale)
        st.header("🏗️ PORTALE CAD")
        
        # STATUS SERVER
        status = get_server_status(bucket)
        st.markdown(f"**Stato:** {status}")
        if "OFFLINE" in status:
            st.error("⚠️ Server locale non risponde.")
        
        st.divider()
        
        # SEZIONE 1: RICHIESTE IN CORSO
        st.subheader("⏳ In Sincronizzazione")
        pending = {k: v for k, v in queue.items() if not v.get('synced', False)}
        if not pending:
            st.caption("Nessuna richiesta pendente.")
        else:
            for code, data in pending.items():
                st.info(f"**{code}**\nAttendere Bridge...")

        # NOTIFICA FILE PRONTI
        ready = {k: v for k, v in queue.items() if v.get('synced', False)}
        for code in list(ready.keys()):
            if st.button(f"✅ {code} PRONTO", key=f"ready_{code}"):
                if code not in history:
                    history.insert(0, code)
                    bucket.blob("metadata/history.json").upload_from_string(json.dumps(history[:20]))
                del queue[code]
                bucket.blob("metadata/sync_queue.json").upload_from_string(json.dumps(queue))
                st.rerun()

        st.divider()

        # SEZIONE 2: STORICO RECENTI
        st.subheader("🕒 Recenti")
        for old_code in history:
            if st.button(f"📄 {old_code}", key=f"hist_{old_code}", use_container_width=True):
                st.session_state.f1_query = old_code # Forza la ricerca
                st.rerun()

    # --- CONTENT AREA ---
    # CSS "CHROME STYLE"
    st.markdown("""
        <style>
        .stApp { background-color: #f8f9fa; }
        .stTabs [data-baseweb="tab-list"] { gap: 2px; background-color: #dee2e6; padding: 5px 5px 0px 5px; border-radius: 5px 5px 0 0; }
        .stTabs [data-baseweb="tab"] { background-color: #e9ecef; border: none; padding: 10px 20px; color: #495057 !important; font-weight: 500 !important; border-radius: 5px 5px 0 0; }
        .stTabs [aria-selected="true"] { background-color: #ffffff !important; color: #1a73e8 !important; border-bottom: 3px solid #1a73e8 !important; }
        .stButton>button { background-color: #1a73e8; color: white !important; border-radius: 4px; border: none; font-weight: 500; height: 40px; }
        .stButton>button:hover { background-color: #1557b0; color: white !important; }
        label, p, h1, h2, h3 { color: #212529 !important; font-family: 'Segoe UI', sans-serif; }
        </style>
        """, unsafe_allow_html=True)

    # RECUPERO CATEGORIE
    try:
        cats_json = bucket.blob("metadata/categories.json").download_as_text()
        lista_categorie = json.loads(cats_json)
    except:
        lista_categorie = ["Aggiornamento categorie in corso..."]

    tab1, tab2 = st.tabs(["🚀 CHECK-IN", "🔍 CHECK-OUT"])

    # --- TAB 1: CHECK-IN ---
    with tab1:
        st.subheader("Caricamento Nuovo Articolo")
        with st.form("form_checkin", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                nome_articolo = st.text_input("Codice Articolo")
                categoria = st.selectbox("Categoria", lista_categorie)
            with col2:
                tags = st.text_input("Tag (separati da virgola)")
                solo_trasferimento = st.checkbox("Solo Trasferimento")
            note = st.text_area("Note Tecniche")
            upload_files = st.file_uploader("Trascina i file", accept_multiple_files=True)
            if st.form_submit_button("INVIA CODICE"):
                if upload_files and nome_articolo:
                    with st.spinner("Sincronizzazione..."):
                        task_data = {"nome_articolo": nome_articolo, "categoria": categoria, "tags": [t.strip() for t in tags.split(",")],"note": note, "solo_trasferimento": solo_trasferimento, "timestamp": time.time()}
                        bucket.blob(f"inbox/{nome_articolo}.json").upload_from_string(json.dumps(task_data, indent=4))
                        for f in upload_files:
                            bucket.blob(f"inbox/{nome_articolo}/{f.name}").upload_from_file(f)
                        st.success(f"Archiviazione per {nome_articolo} avviata.")
                else:
                    st.error("Dati incompleti.")

    # --- TAB 2: CHECK-OUT ---
    with tab2:
        st.subheader("Ricerca e Prelievo")
        try:
            idx_blob = bucket.blob("metadata/archivio_index.json").download_as_text()
            index_data = json.loads(idx_blob)["components"]
        except:
            st.error("Indice non disponibile.")
            index_data = []

        c1, c2 = st.columns(2)
        with c1: 
            # Utilizza il valore dalla session_state se presente (per la cronologia)
            n1 = st.text_input("Ricerca Nome 1", value=st.session_state.f1_query, key="f1").lower()
            # Reset della query dopo l'uso per permettere nuove ricerche
            st.session_state.f1_query = ""
            
        with c2: n2 = st.text_input("Ricerca Nome 2", key="f2").lower()
        t1, t2, t3 = st.columns(3)
        with t1: tag1 = t1.text_input("Tag 1", key="f3").lower()
        with t2: tag2 = t2.text_input("Tag 2", key="f4").lower()
        with t3: tag3 = t3.text_input("Tag 3", key="f5").lower()

        filtered = []
        for item in index_data:
            full_text = (item.get('code', '') + " " + " ".join(item.get('tags', []))).lower()
            if (n1 in full_text and n2 in full_text) and (tag1 in full_text and tag2 in full_text and tag3 in full_text):
                filtered.append(item)

        st.info(f"📍 Risultati trovati: {len(filtered)} | Elementi in coda prelievo: {len(st.session_state.download_queue)}")

        with st.container(height=500, border=True):
            for item in filtered[:st.session_state.limit_results]:
                col_info, col_btn_pre, col_btn_sel = st.columns([4, 1, 1])
                with col_info:
                    st.write(f"📦 **{item['code']}**")
                    st.caption(f"{item['category']} | Tags: {', '.join(item['tags'][:3])}...")
                with col_btn_pre:
                    if st.button("👁️ Anteprima", key=f"pre_{item['code']}"):
                        preview_dialog(item, bucket)
                with col_btn_sel:
                    is_selected = item['code'] in st.session_state.download_queue
                    label = "✅ Selezionato" if is_selected else "📥 Seleziona"
                    if st.button(label, key=f"sel_{item['code']}", type="secondary" if is_selected else "primary"):
                        if is_selected:
                            st.session_state.download_queue.remove(item['code'])
                        else:
                            st.session_state.download_queue.add(item['code'])
                        st.rerun()

        if len(filtered) > st.session_state.limit_results:
            st.button("Mostra altri risultati...", on_click=show_more)

        st.write("---")
        if st.button("🚀 GENERA LINK PER DOWNLOAD (ZIP)"):
            if st.session_state.download_queue:
                req_id = int(time.time())
                codes_to_download = list(st.session_state.download_queue)
                req = {"items": codes_to_download, "request_id": req_id, "timestamp": time.time()}
                bucket.blob(f"requests/req_{req_id}.json").upload_from_string(json.dumps(req, indent=4))
                st.session_state['last_req_id'] = req_id
                st.success(f"Richiesta {req_id} inviata. Bridge in elaborazione.")
            else:
                st.error("Coda di prelievo vuota. Seleziona almeno un articolo.")
        
        if 'last_req_id' in st.session_state:
            req_id = st.session_state['last_req_id']
            res_blob = bucket.blob(f"responses/{req_id}.json")
            if res_blob.exists():
                res_data = json.loads(res_blob.download_as_text())
                st.link_button("🔥 SCARICA IL TUO ZIP PRONTO", res_data['url'], use_container_width=True)
                if st.button("Svuota coda prelievo"):
                    st.session_state.download_queue.clear()
                    st.rerun()
            else:
                if st.button("🔄 AGGIORNA STATO PRELIEVO"):
                    st.rerun()
