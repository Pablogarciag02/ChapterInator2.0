# app.py
# Ebook Generation Pipeline Streamlit Application

import streamlit as st
import requests
import json
import time
from concurrent.futures import ThreadPoolExecutor

import hashlib

def check_password():
    """Returns True if the user had the correct password."""
    
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if hashlib.sha256(st.session_state["password"].encode()).hexdigest() == st.secrets["password_hash"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if st.session_state.get("password_correct", False):
        return True

    st.text_input("Password", type="password", on_change=password_entered, key="password")
    if "password_correct" in st.session_state:
        st.error("Password incorrect")
    return False

# --- CONFIGURATION & CONSTANTS ---

# Set Streamlit page configuration
st.set_page_config(
    page_title="Ebook Generation Pipeline",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# API Authentication and Endpoints from documentation
API_KEY = st.secrets["API_KEY"]
API_BASE_URL = "https://app.wordware.ai/api/released-app"

APP_IDS = {
    "compendio_to_markdown": "ac114c48-be3a-4ab5-98ee-02a7d11c8dd7",
    "project_brief_to_markdown": "b198e35c-9089-4dc4-a281-92bbb04d7528",
    "mapping_referencias": "da1c1988-c58f-4574-be2c-822cd743179c",
    "mapping_citas": "d5202c5b-316c-466e-a85a-3d2e3d7fe405",
    "mapping_tablas": "3311cdd6-39ed-47bc-9173-c2de11afe82a",
    "mapping_logic": "c36eb029-1b08-4337-af35-4df4be3bef38",
    "theme_selector": "a9ba5428-5286-46f3-b3ca-1ba824c686d9",
    "chapter_creator": "75ad4354-dd42-406e-be67-67073b3b82a2",
    # NOTE: Placeholder as per documentation. Update if a real ID is provided.
    "table_generator": "660116bf-1f90-496b-aa12-d357044867ef" 
}

# --- SESSION STATE MANAGEMENT ---

def initialize_session_state():
    """Initializes all required session state variables with default values."""
    defaults = {
        # General app state
        'current_stage': 1,
        
        # Stage Status Tracking
        'stage_1_status': 'pending', 'stage_2_status': 'pending', 'stage_3_status': 'pending',
        'stage_4_status': 'pending', 'stage_5_status': 'pending',
        'stage_2_1_status': 'pending', 'stage_2_2_status': 'pending',
        'stage_2_3_status': 'pending', 'stage_2_4_status': 'pending',

        # Primary Data Storage
        'compendio_md': "", 'project_brief_md': "", 'mapping_combined': "",
        'skeleton': {}, 'generated_chapters': {}, 'final_ebook': "",

        # User settings for Stage 3
        'topic_input': "", 'reference_count': 25, 'page_count': "40-50", 'subtemas_enabled': False,

        # File management
        'uploaded_files': {},

        # Intermediate outputs for modular recovery
        'stage_1_1_output': "", 'stage_1_2_output': "",
        'mapping_referencias': "", 'mapping_citas': "", 'mapping_tablas': "",

        # Sequential Chapter Generation Management
        'chapter_sequence': [], 'current_chapter_index': 0, 'previous_context': "",
        'chapters_completed': [], 'book_complete': False
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

def clear_all_session_data():
    """Resets the entire pipeline by clearing relevant session state keys."""
    keys_to_clear = [key for key in st.session_state.keys() if key.startswith((
        'stage_', 'compendio_', 'project_', 'mapping_', 'skeleton', 'generated_', 
        'final_', 'topic_', 'reference_', 'page_', 'subtemas_', 'uploaded_', 
        'chapter_', 'current_', 'previous_', 'book_'))]
    
    for key in keys_to_clear:
        del st.session_state[key]
    
    st.success("All pipeline data has been cleared. Please refresh the page to start over.")
    time.sleep(2)
    st.rerun()

# --- FILE UPLOAD HELPERS ---

def upload_to_0x0(file):
    """Uploads a file to 0x0.st."""
    try:
        file.seek(0)
        files = {"file": (file.name, file, file.type)}
        response = requests.post("https://0x0.st", files=files, timeout=60)
        if response.status_code == 200 and response.text.strip().startswith("https://"):
            return response.text.strip()
    except Exception as e:
        st.toast(f"Error with 0x0.st: {e}", icon="🔥")
    return None

def upload_to_catbox(file):
    """Uploads a file to catbox.moe."""
    try:
        file.seek(0)
        files = {"fileToUpload": (file.name, file, file.type)}
        data = {"reqtype": "fileupload"}
        response = requests.post("https://catbox.moe/user/api.php", files=files, data=data, timeout=60)
        if response.status_code == 200 and response.text.strip().startswith("https://"):
            return response.text.strip()
    except Exception as e:
        st.toast(f"Error with catbox.moe: {e}", icon="🔥")
    return None

def upload_to_tmpfiles(file):
    """Uploads a file to tmpfiles.org."""
    try:
        file.seek(0)
        files = {"file": (file.name, file, file.type)}
        response = requests.post("https://tmpfiles.org/api/v1/upload", files=files, timeout=60)
        if response.status_code == 200:
            data = response.json()
            url = data.get("data", {}).get("url", "")
            if url:
                return url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/")
    except Exception as e:
        st.toast(f"Error with tmpfiles.org: {e}", icon="🔥")
    return None

def upload_file_with_fallback(file):
    """Tries multiple upload services until one succeeds."""
    services = [upload_to_0x0, upload_to_catbox, upload_to_tmpfiles]
    for service in services:
        service_name = service.__name__.replace('upload_to_', '').replace('_', ' ').title()
        with st.spinner(f"Uploading via {service_name}..."):
            url = service(file)
            if url:
                st.toast(f"Successfully uploaded via {service_name}!", icon="✅")
                return url
    st.error("All file upload services failed. Please check your network or try again later.")
    return None

# --- API CALLER & STREAMING ---

def process_wordware_api(app_id, inputs, stream_container=None):
    """
    Calls a Wordware API endpoint, handles streaming responses, and returns the final output.
    If a stream_container is provided, it writes chunks to it in real-time.
    """
    url = f"{API_BASE_URL}/{app_id}/run"
    headers = {"Authorization": f"Bearer {API_KEY}"}
    payload = {"inputs": inputs}
    
    try:
        response = requests.post(url, json=payload, headers=headers, stream=True, timeout=300)
        response.raise_for_status()

        final_output = None
        full_response_text = ""
        
        # Use a generator function for streaming to st.write_stream
        def stream_generator():
            nonlocal final_output
            for line in response.iter_lines():
                if line:
                    try:
                        content = json.loads(line.decode('utf-8'))
                        value = content.get('value', {})
                        
                        if value.get('type') == 'chunk':
                            yield value.get('value', '')
                        elif value.get('type') == 'outputs':
                            final_output = value
                    except json.JSONDecodeError:
                        st.warning(f"Could not decode JSON line: {line}")
        
        if stream_container:
            stream_container.write_stream(stream_generator)
        else:
            # If not streaming to UI, just consume the generator to get the final output
            for _ in stream_generator():
                pass
        if final_output:
            # Assuming the main output is in a key named 'output', 'text', or the first value
            output_data = final_output.get('values', {})
            if 'output' in output_data:
                return output_data['output']
            elif 'text' in output_data:
                return output_data['text']
            # Fallback for varied output structures
            elif output_data:
                # first_key = next(iter(output_data))
                # return output_data[first_key]
                return output_data
        # if final_output:
        #     # Assuming the main output is in a key named 'output', 'text', or the first value
        #     output_data = final_output.get('values', {})
        #     if 'output' in output_data:
        #         return output_data['output']
        #     elif 'text' in output_data:
        #         return output_data['text']
        #     # Fallback for varied output structures
        #     elif output_data:
        #         # first_key = next(iter(output_data))
        #         # return output_data[first_key]
        #         return output_data

        return None

    except requests.exceptions.RequestException as e:
        st.error(f"API Request Failed: {e}")
        try:
            st.error(f"Error details: {response.json()}")
        except:
            st.error(f"Error details: {response.text}")
        return None

# --- UI RENDERING FUNCTIONS ---

def render_status_icon(status):
    """Returns a status icon based on the stage status."""
    if status == 'completed':
        return "✅"
    elif status == 'in_progress':
        return "🔄"
    elif status == 'error':
        return "❌"
    return "⚪"

def render_progress_indicator():
    """Displays the main pipeline progress bar at the top."""
    st.subheader("Ebook Generation Progress")
    cols = st.columns(5)
    stages = [
        ("1. Content", st.session_state.stage_1_status),
        ("2. Mapping", st.session_state.stage_2_status),
        ("3. Structure", st.session_state.stage_3_status),
        ("4. Chapters", st.session_state.stage_4_status),
        ("5. Assembly", st.session_state.stage_5_status)
    ]
    for col, (name, status) in zip(cols, stages):
        with col:
            icon = render_status_icon(status)
            st.markdown(f"**{name}** {icon}")
    st.divider()

def render_sidebar():
    """Renders the navigation sidebar."""
    with st.sidebar:
        st.title("📚 Pipeline Stages")
        st.markdown("Navigate through the ebook generation process.")

        # Stage 1
        st.button("Stage 1: Content Processing", on_click=lambda: st.session_state.update(current_stage=1), use_container_width=True, type="primary" if st.session_state.current_stage == 1 else "secondary")
        
        # Stage 2
        st.button("Stage 2: Reference Mapping", on_click=lambda: st.session_state.update(current_stage=2), use_container_width=True, disabled=st.session_state.stage_1_status != 'completed', type="primary" if st.session_state.current_stage == 2 else "secondary")
        
        # Stage 3
        st.button("Stage 3: Structure Creation", on_click=lambda: st.session_state.update(current_stage=3), use_container_width=True, disabled=st.session_state.stage_2_status != 'completed', type="primary" if st.session_state.current_stage == 3 else "secondary")
        
        # Stage 4
        st.button("Stage 4: Chapter Generation", on_click=lambda: st.session_state.update(current_stage=4), use_container_width=True, disabled=st.session_state.stage_3_status != 'completed', type="primary" if st.session_state.current_stage == 4 else "secondary")
        
        # Stage 5
        st.button("Stage 5: Final Assembly", on_click=lambda: st.session_state.update(current_stage=5), use_container_width=True, disabled=not st.session_state.book_complete, type="primary" if st.session_state.current_stage == 5 else "secondary")
        
        st.divider()
        st.warning("Clearing data will reset the entire process and cannot be undone.")
        if st.button("🔄 Clear All Data & Restart", use_container_width=True, type="primary"):
            clear_all_session_data()

## --- Stage 1: Content Processing ---
def render_stage_1():
    st.header("Stage 1: Content Processing")
    st.markdown("Upload your source PDF documents. The 'Compendio' is required, while the 'Project Brief' is optional but recommended for better context.")

    compendio_file = st.file_uploader("Upload Compendio PDF (Required)", type="pdf", key="compendio_uploader")
    project_brief_file = st.file_uploader("Upload Project Brief PDF (Optional)", type="pdf", key="project_brief_uploader")

    if st.button("Process Source Documents", disabled=(not compendio_file)):
        st.session_state.stage_1_status = 'in_progress'
        
        compendio_url = upload_file_with_fallback(compendio_file)
        if not compendio_url:
            st.session_state.stage_1_status = 'error'
            st.error("Failed to upload the Compendio PDF. Cannot proceed.")
            return

        st.session_state.uploaded_files['compendio'] = {"url": compendio_url, "name": compendio_file.name}
        
        brief_url = None
        if project_brief_file:
            brief_url = upload_file_with_fallback(project_brief_file)
            if brief_url:
                st.session_state.uploaded_files['project_brief'] = {"url": brief_url, "name": project_brief_file.name}

        # Use ThreadPoolExecutor to run API calls in parallel
        with ThreadPoolExecutor(max_workers=3) as executor:
            st.info("Starting parallel processing of documents... This may take several minutes.")
            
            # Prepare inputs
            compendio_input = {"type": "file", "file_type": "application/pdf", "file_url": compendio_url, "file_name": compendio_file.name}
            
            # Submit jobs
            future1 = executor.submit(process_wordware_api, APP_IDS["compendio_to_markdown"], {"CompendioPDF": compendio_input})
            future2 = executor.submit(process_wordware_api, APP_IDS["compendio_to_markdown"], {"CompendioPDF": compendio_input})
            future3 = None
            if brief_url:
                brief_input = {"type": "file", "file_type": "application/pdf", "file_url": brief_url, "file_name": project_brief_file.name}
                future3 = executor.submit(process_wordware_api, APP_IDS["project_brief_to_markdown"], {"ProjectBriefPDF": brief_input})
            
            # # Retrieve results
            # with st.status("Processing Compendio (Part 1/2)..."):
            #     st.session_state.stage_1_1_output = result1 if isinstance(result1, str) else list(result1.values())[0]
            #     # st.session_state.stage_1_1_output = future1.result()
            # with st.status("Processing Compendio (Part 2/2)..."):
            #     st.session_state.stage_1_2_output = result2 if isinstance(result2, str) else list(result2.values())[0]
            #     # st.session_state.stage_1_2_output = future2.result()
            # if future3:
            #     with st.status("Processing Project Brief..."):
            #         st.session_state.project_brief_md = future3.result()
            # Retrieve results
            with st.status("Processing Compendio (Part 1/2)..."):
                result1 = future1.result()
                st.session_state.stage_1_1_output = result1 if isinstance(result1, str) else list(result1.values())[0]
            with st.status("Processing Compendio (Part 2/2)..."):
                result2 = future2.result()
                st.session_state.stage_1_2_output = result2 if isinstance(result2, str) else list(result2.values())[0]

        if st.session_state.stage_1_1_output and st.session_state.stage_1_2_output:
            st.session_state.compendio_md = st.session_state.stage_1_1_output + "\n\n" + st.session_state.stage_1_2_output
            st.session_state.stage_1_status = 'completed'
            st.success("Stage 1 Completed! All documents processed successfully.")
        else:
            st.session_state.stage_1_status = 'error'
            st.error("An error occurred during document processing. Check the logs above.")
            
        st.rerun()

    if st.session_state.stage_1_status == 'completed':
        st.success("✅ Stage 1 is complete. You can now proceed to Stage 2.")
        with st.expander("View Processed Compendio Markdown"):
            st.markdown(st.session_state.compendio_md)
            st.download_button(
                label="Download Compendio.md",
                data=st.session_state.compendio_md.encode('utf-8'),
                file_name="compendio.md",
                mime="text/markdown"
            )
        if st.session_state.project_brief_md:
            with st.expander("View Processed Project Brief Markdown"):
                st.markdown(st.session_state.project_brief_md)
                st.download_button(
                    label="Download Project_Brief.md",
                    data=st.session_state.project_brief_md.encode('utf-8'),
                    file_name="project_brief.md",
                    mime="text/markdown"
                )

## --- Stage 2: Reference Mapping ---
def render_stage_2():
    st.header("Stage 2: Reference Mapping")
    st.markdown("This stage automatically extracts and maps all references, citations, and tables from the processed content. Click the button below to begin.")

    if st.button("Start Reference Mapping", disabled=(st.session_state.stage_1_status != 'completed')):
        st.session_state.stage_2_status = 'in_progress'
        
        # Run 2.1 Mapping_Referencias
        with st.spinner("Step 2.1: Extracting Bibliography References..."):
            inputs_2_1 = {"compendio": st.session_state.compendio_md, "projectBrief": st.session_state.project_brief_md}
            result = process_wordware_api(APP_IDS["mapping_referencias"], inputs_2_1)
            if result:
                st.session_state.mapping_referencias = result
                st.session_state.stage_2_1_status = 'completed'
                st.toast("Step 2.1: References extracted.", icon="✅")
            else:
                st.session_state.stage_2_status = 'error'
                st.error("Failed at Step 2.1. Cannot proceed.")
                return

        # Run 2.2 Mapping_Citas
        with st.spinner("Step 2.2: Mapping In-Text Citations..."):
            inputs_2_2 = {
                "compendio": st.session_state.compendio_md, 
                "projectBrief": st.session_state.project_brief_md,
                "2.1Mapping_Referencias": json.dumps(st.session_state.mapping_referencias)
            }
            result = process_wordware_api(APP_IDS["mapping_citas"], inputs_2_2)
            if result:
                st.session_state.mapping_citas = result
                st.session_state.stage_2_2_status = 'completed'
                st.toast("Step 2.2: Citations mapped.", icon="✅")
            else:
                st.session_state.stage_2_status = 'error'
                st.error("Failed at Step 2.2. Cannot proceed.")
                return
        
        # Run 2.3 Mapping_Tablas
        with st.spinner("Step 2.3: Mapping Tables and Figures..."):
            inputs_2_3 = {
                "compendio": st.session_state.compendio_md,
                "projectBrief": st.session_state.project_brief_md,
                "2.1Mapping_Referencias": json.dumps(st.session_state.mapping_referencias),
                "2.2Mapping_Citas": json.dumps(st.session_state.mapping_citas)
            }
            result = process_wordware_api(APP_IDS["mapping_tablas"], inputs_2_3)
            if result:
                st.session_state.mapping_tablas = result
                st.session_state.stage_2_3_status = 'completed'
                st.toast("Step 2.3: Tables mapped.", icon="✅")
            else:
                st.session_state.stage_2_status = 'error'
                st.error("Failed at Step 2.3. Cannot proceed.")
                return

        # Run 2.4 MappingLogic
        with st.spinner("Step 2.4: Combining All Mappings..."):
            inputs_2_4 = {
                "mapeoCitas": json.dumps(st.session_state.mapping_citas),
                "mapeoReferencias": json.dumps(st.session_state.mapping_referencias),
                "mapeoTablas": json.dumps(st.session_state.mapping_tablas)
            }
            result = process_wordware_api(APP_IDS["mapping_logic"], inputs_2_4)
            if result:
                st.session_state.mapping_combined = result
                st.session_state.stage_2_4_status = 'completed'
                st.session_state.stage_2_status = 'completed'
                st.success("Stage 2 Completed! All references, citations, and tables have been mapped.")
            else:
                st.session_state.stage_2_status = 'error'
                st.error("Failed at Step 2.4. Could not combine mappings.")
        st.rerun()

    if st.session_state.stage_2_status == 'completed':
        st.success("✅ Stage 2 is complete. You can now proceed to Stage 3.")
        with st.expander("View Combined Mapping Data (JSON)"):
            # st.json(st.session_state.mapping_combined)
            # Show only Merger output instead of the full response
            merger_output = st.session_state.mapping_combined.get('Merger', {}).get('output', st.session_state.mapping_combined)
            st.json(merger_output)

#Version viejita que recupere que solo demuestra el esqueletoMaestro en formato Json.
## --- Stage 3: Structure Creation ---
def render_stage_3():
    st.header("Stage 3: Ebook Structure Creation")
    st.markdown("Define the core parameters for your ebook. The AI will generate a detailed skeleton, including chapter structure, narrative arc, and reference distribution.")

    with st.form("structure_form"):
        st.text_area(
            "Main Topics & Subtopics", 
            key='topic_input',
            help="Enter main topics, one per line. If 'AI Generates Subtopics' is unchecked, add subtopics indented below each main topic.",
            height=200
        )
        st.checkbox("AI Generates Subtopics", key='subtemas_enabled', help="Check this to let the AI generate subtopics based on the main topics you provide.")
        
        cols = st.columns(2)
        with cols[0]:
            st.slider("Reference Density", 1, 50, key='reference_count', help="Desired total number of references in the ebook.")
        with cols[1]:
            st.select_slider(
                "Target Page Count", 
                options=["20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100+"],
                key='page_count',
                help="Estimated page range for the final ebook."
            )
        
        submitted = st.form_submit_button("Generate Ebook Skeleton", use_container_width=True, type="primary")

    if submitted:
        if not st.session_state.topic_input:
            st.warning("Please provide main topics before generating the skeleton.")
            return

        st.session_state.stage_3_status = 'in_progress'
        
        inputs = {
            "compendio": st.session_state.compendio_md,
            "projectBrief": st.session_state.project_brief_md,
            "topicInput": st.session_state.topic_input,
            "referenceCount": st.session_state.reference_count,
            "MapeoContenido": json.dumps(st.session_state.mapping_combined),
            "pageCount": st.session_state.page_count,
            "subtemas": not st.session_state.subtemas_enabled # Inverted logic from doc
        }
        
        st.info("Generating the ebook skeleton... This might take a moment.")
        stream_container = st.empty()
        
        result = process_wordware_api(APP_IDS["theme_selector"], inputs, stream_container)
        
        if result:
            # For Stage 3, we need the full API response with all objects
            # But we need to reconstruct it from the streaming response
            # The result here is just the first object, so we store it but handle parsing differently
            st.session_state.skeleton = result
            # Extract chapter sequence for Stage 4
            try:
                # The structure is nested, so we access it carefully
                structure = result.get('EsqueletoMaestro', {}).get('esqueletoLogica', {}).get('estructura_capitulos', [])
                # The structure seems to be a list of strings, let's parse them
                chapter_list = []
                for item in structure:
                    if not item.strip().startswith(('  ', '\t')): # Assuming main topics are chapters
                        # A simple way to create an identifier
                        chapter_name = "capitulo_" + str(len(chapter_list) + 1)
                        chapter_list.append(chapter_name)
                
                st.session_state.chapter_sequence = chapter_list
                st.session_state.stage_3_status = 'completed'
                st.success("Stage 3 Completed! Ebook skeleton generated successfully.")
            except Exception as e:
                st.session_state.stage_3_status = 'error'
                st.error(f"Could not parse chapter structure from skeleton: {e}")
                st.json(result)
        else:
            st.session_state.stage_3_status = 'error'
            st.error("Failed to generate ebook skeleton.")
        st.rerun()

    # if st.session_state.stage_3_status == 'completed':
    #     st.success("✅ Stage 3 is complete. You can now proceed to Stage 4.")
    #     with st.expander("View Generated Ebook Skeleton", expanded=True):
    #         st.json(st.session_state.skeleton)
    #     st.info(f"The skeleton defines {len(st.session_state.chapter_sequence)} chapters to be generated.")
    if st.session_state.stage_3_status == 'completed':
        st.success("✅ Stage 3 is complete. You can now proceed to Stage 4.")
        with st.expander("View Generated Ebook Skeleton", expanded=True):
            # Show only EsqueletoMaestro instead of the full response
            esqueleto_maestro = st.session_state.skeleton.get('EsqueletoMaestro', {})
            st.json(esqueleto_maestro)
        st.info(f"The skeleton defines {len(st.session_state.chapter_sequence)} chapters to be generated.")


# # # #VErsion funcional que demustra solo el esqueletoMaestro en formato json
# # # ## --- Stage 3: Structure Creation ---
# # # def render_stage_3():
# # #     st.header("Stage 3: Ebook Structure Creation")
# # #     st.markdown("Define the core parameters for your ebook. The AI will generate a detailed skeleton, including chapter structure, narrative arc, and reference distribution.")

# # #     with st.form("structure_form"):
# # #         st.text_area(
# # #             "Main Topics & Subtopics", 
# # #             key='topic_input',
# # #             help="Enter main topics, one per line. If 'AI Generates Subtopics' is unchecked, add subtopics indented below each main topic.",
# # #             height=200
# # #         )
# # #         st.checkbox("AI Generates Subtopics", key='subtemas_enabled', help="Check this to let the AI generate subtopics based on the main topics you provide.")
        
# # #         cols = st.columns(2)
# # #         with cols[0]:
# # #             st.slider("Reference Density", 1, 50, key='reference_count', help="Desired total number of references in the ebook.")
# # #         with cols[1]:
# # #             st.select_slider(
# # #                 "Target Page Count", 
# # #                 options=["20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100+"],
# # #                 key='page_count',
# # #                 help="Estimated page range for the final ebook."
# # #             )
        
# # #         submitted = st.form_submit_button("Generate Ebook Skeleton", use_container_width=True, type="primary")

# # #     if submitted:
# # #         if not st.session_state.topic_input:
# # #             st.warning("Please provide main topics before generating the skeleton.")
# # #             return

# # #         st.session_state.stage_3_status = 'in_progress'
        
# # #         inputs = {
# # #             "compendio": st.session_state.compendio_md,
# # #             "projectBrief": st.session_state.project_brief_md,
# # #             "topicInput": st.session_state.topic_input,
# # #             "referenceCount": st.session_state.reference_count,
# # #             "MapeoContenido": json.dumps(st.session_state.mapping_combined),
# # #             "pageCount": st.session_state.page_count,
# # #             "subtemas": not st.session_state.subtemas_enabled # Inverted logic from doc
# # #         }
        
# # #         st.info("Generating the ebook skeleton... This might take a moment.")
# # #         stream_container = st.empty()
        
# # #         result = process_wordware_api(APP_IDS["theme_selector"], inputs, stream_container)
        
# # #         if result:
# # #             # For Stage 3, we need the full API response with all objects
# # #             # But we need to reconstruct it from the streaming response
# # #             # The result here is just the first object, so we store it but handle parsing differently
# # #             st.session_state.skeleton = result
# # #             # Extract chapter sequence for Stage 4
# # #             try:
# # #                 # The structure is nested, so we access it carefully
# # #                 structure = result.get('EsqueletoMaestro', {}).get('esqueletoLogica', {}).get('estructura_capitulos', [])
# # #                 # The structure seems to be a list of strings, let's parse them
# # #                 chapter_list = []
# # #                 for item in structure:
# # #                     if not item.strip().startswith(('  ', '\t')): # Assuming main topics are chapters
# # #                         # A simple way to create an identifier
# # #                         chapter_name = "capitulo_" + str(len(chapter_list) + 1)
# # #                         chapter_list.append(chapter_name)
                
# # #                 st.session_state.chapter_sequence = chapter_list
# # #                 st.session_state.stage_3_status = 'completed'
# # #                 st.success("Stage 3 Completed! Ebook skeleton generated successfully.")
# # #             except Exception as e:
# # #                 st.session_state.stage_3_status = 'error'
# # #                 st.error(f"Could not parse chapter structure from skeleton: {e}")
# # #                 st.json(result)
# # #         else:
# # #             st.session_state.stage_3_status = 'error'
# # #             st.error("Failed to generate ebook skeleton.")
# # #         st.rerun()

# # #     # if st.session_state.stage_3_status == 'completed':
# # #     #     st.success("✅ Stage 3 is complete. You can now proceed to Stage 4.")
# # #     #     with st.expander("View Generated Ebook Skeleton", expanded=True):
# # #     #         st.json(st.session_state.skeleton)
# # #     #     st.info(f"The skeleton defines {len(st.session_state.chapter_sequence)} chapters to be generated.")
# # #     if st.session_state.stage_3_status == 'completed':
# # #         st.success("✅ Stage 3 is complete. You can now proceed to Stage 4.")
# # #         with st.expander("View Generated Ebook Skeleton", expanded=True):
# # #             # Show only EsqueletoMaestro instead of the full response
# # #             esqueleto_maestro = st.session_state.skeleton.get('EsqueletoMaestro', {})
# # #             st.json(esqueleto_maestro)
# # #         st.info(f"The skeleton defines {len(st.session_state.chapter_sequence)} chapters to be generated.")

# #VErsion que permite edicion pero arruina la cuenta cuando se edita.
# def render_stage_3():
#     st.header("Stage 3: Ebook Structure Creation")
#     st.markdown("Define the core parameters for your ebook. The AI will generate a detailed skeleton, including chapter structure, narrative arc, and reference distribution.")

#     with st.form("structure_form"):
#         st.text_area(
#             "Main Topics & Subtopics", 
#             key='topic_input',
#             help="Enter main topics, one per line. If 'AI Generates Subtopics' is unchecked, add subtopics indented below each main topic.",
#             height=200
#         )
#         st.checkbox("AI Generates Subtopics", key='subtemas_enabled', help="Check this to let the AI generate subtopics based on the main topics you provide.")
        
#         cols = st.columns(2)
#         with cols[0]:
#             st.slider("Reference Density", 1, 50, key='reference_count', help="Desired total number of references in the ebook.")
#         with cols[1]:
#             st.select_slider(
#                 "Target Page Count", 
#                 options=["20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100+"],
#                 key='page_count',
#                 help="Estimated page range for the final ebook."
#             )
        
#         submitted = st.form_submit_button("Generate Ebook Skeleton", use_container_width=True, type="primary")

#     if submitted:
#         if not st.session_state.topic_input:
#             st.warning("Please provide main topics before generating the skeleton.")
#             return

#         st.session_state.stage_3_status = 'in_progress'
        
#         inputs = {
#             "compendio": st.session_state.compendio_md,
#             "projectBrief": st.session_state.project_brief_md,
#             "topicInput": st.session_state.topic_input,
#             "referenceCount": st.session_state.reference_count,
#             "MapeoContenido": json.dumps(st.session_state.mapping_combined),
#             "pageCount": st.session_state.page_count,
#             "subtemas": not st.session_state.subtemas_enabled # Inverted logic from doc
#         }
        
#         st.info("Generating the ebook skeleton... This might take a moment.")
#         stream_container = st.empty()
        
#         result = process_wordware_api(APP_IDS["theme_selector"], inputs, stream_container)
        
#         if result:
#             st.session_state.skeleton = result
#             # Extract chapter sequence for Stage 4
#             try:
#                 # structure = result.get('EsqueletoMaestro', {}).get('esqueletoLogica', {}).get('estructura_capitulos', [])
#                 # chapter_list = []
#                 # for item in structure:
#                 #     if not item.strip().startswith(('  ', '\t')):
#                 #         chapter_name = "capitulo_" + str(len(chapter_list) + 1)
#                 #         chapter_list.append(chapter_name)
#                 # Simple, reliable logic
#                 estructura_capitulos = result.get('EsqueletoMaestro', {}).get('esqueletoLogica', {}).get('estructura_capitulos', [])
#                 chapter_list = [f"capitulo_{i+1}" for i in range(len(estructura_capitulos))]
                
#                 st.session_state.chapter_sequence = chapter_list
#                 st.session_state.stage_3_status = 'completed'
#                 st.success("Stage 3 Completed! Ebook skeleton generated successfully.")
#             except Exception as e:
#                 st.session_state.stage_3_status = 'error'
#                 st.error(f"Could not parse chapter structure from skeleton: {e}")
#                 st.json(result)
#         else:
#             st.session_state.stage_3_status = 'error'
#             st.error("Failed to generate ebook skeleton.")
#         st.rerun()

#     if st.session_state.stage_3_status == 'completed':
#         st.success("✅ Stage 3 is complete. You can now proceed to Stage 4.")
        
#         # Initialize edit mode tracking if not exists
#         if 'skeleton_edit_mode' not in st.session_state:
#             st.session_state.skeleton_edit_mode = False
        
#         esqueleto_maestro = st.session_state.skeleton.get('EsqueletoMaestro', {})
#         esqueleto_logica = esqueleto_maestro.get('esqueletoLogica', {})
        
#         with st.expander("View & Edit Ebook Skeleton", expanded=True):
#             col1, col2 = st.columns([3, 1])
            
#             with col2:
#                 edit_button_label = "Save Changes" if st.session_state.skeleton_edit_mode else "Edit Skeleton"
#                 if st.button(edit_button_label, key="edit_skeleton_btn"):
#                     if st.session_state.skeleton_edit_mode:
#                         # Save mode - update session state with edited content
#                         edited_chapters = st.session_state.get("edit_chapters", "")
#                         edited_narrative = st.session_state.get("edit_narrative", "")
                        
#                         # Update the skeleton data
#                         new_chapters = [line.strip() for line in edited_chapters.split('\n') if line.strip()]
#                         st.session_state.skeleton['EsqueletoMaestro']['esqueletoLogica']['estructura_capitulos'] = new_chapters
#                         st.session_state.skeleton['EsqueletoMaestro']['esqueletoLogica']['arco_narrativo'] = edited_narrative
                        
#                         # Update chapter sequence for Stage 4
#                         chapter_list = []
#                         for item in new_chapters:
#                             if not item.strip().startswith(('  ', '\t')):
#                                 chapter_name = "capitulo_" + str(len(chapter_list) + 1)
#                                 chapter_list.append(chapter_name)
#                         st.session_state.chapter_sequence = chapter_list
                        
#                         # Exit edit mode
#                         st.session_state.skeleton_edit_mode = False
#                         st.rerun()
#                     else:
#                         # Enter edit mode
#                         st.session_state.skeleton_edit_mode = True
#                         st.rerun()
            
#             # Chapter Structure Section
#             st.markdown("#### Chapter Structure")
#             if st.session_state.skeleton_edit_mode:
#                 chapters_text = '\n'.join(esqueleto_logica.get('estructura_capitulos', []))
#                 st.text_area(
#                     "Edit chapter structure (one item per line):",
#                     value=chapters_text,
#                     height=200,
#                     key="edit_chapters"
#                 )
#             else:
#                 chapters = esqueleto_logica.get('estructura_capitulos', [])
#                 for chapter in chapters:
#                     st.write(chapter)
            
#             # Narrative Arc Section
#             st.markdown("#### Narrative Arc")
#             if st.session_state.skeleton_edit_mode:
#                 st.text_area(
#                     "Edit narrative arc:",
#                     value=esqueleto_logica.get('arco_narrativo', ''),
#                     height=100,
#                     key="edit_narrative"
#                 )
#             else:
#                 st.write(esqueleto_logica.get('arco_narrativo', 'No narrative arc defined.'))
            
#             # Estimated Metrics (Read-only)
#             st.markdown("#### Estimated Metrics")
#             metricas = esqueleto_logica.get('metricas_estimadas', {})
#             col1, col2, col3 = st.columns(3)
#             with col1:
#                 st.metric("Total Words", metricas.get('palabras_totales', 'N/A'))
#             with col2:
#                 st.metric("Total Pages", metricas.get('paginas_totales', 'N/A'))
#             with col3:
#                 st.metric("Chapters", len(st.session_state.chapter_sequence))
            
#             # Reference Mapping (Collapsible, Read-only)
#             with st.expander("Reference Distribution"):
#                 ref_mapping = esqueleto_logica.get('distribuicion_referencias', {}).get('referenciasMapeo', [])
#                 if ref_mapping:
#                     for i, ref in enumerate(ref_mapping, 1):
#                         st.write(f"Chapter {i}: {ref}")
#                 else:
#                     st.write("No reference mapping available.")
        
#         st.info(f"The skeleton defines {len(st.session_state.chapter_sequence)} chapters to be generated.")

# #Experimental version with structured editor that maintains chapter count
# def render_stage_3():
#     st.header("Stage 3: Ebook Structure Creation")
#     st.markdown("Define the core parameters for your ebook. The AI will generate a detailed skeleton, including chapter structure, narrative arc, and reference distribution.")

#     with st.form("structure_form"):
#         st.text_area(
#             "Main Topics & Subtopics", 
#             key='topic_input',
#             help="Enter main topics, one per line. If 'AI Generates Subtopics' is unchecked, add subtopics indented below each main topic.",
#             height=200
#         )
#         st.checkbox("AI Generates Subtopics", key='subtemas_enabled', help="Check this to let the AI generate subtopics based on the main topics you provide.")
        
#         cols = st.columns(2)
#         with cols[0]:
#             st.slider("Reference Density", 1, 50, key='reference_count', help="Desired total number of references in the ebook.")
#         with cols[1]:
#             st.select_slider(
#                 "Target Page Count", 
#                 options=["20-30", "30-40", "40-50", "50-60", "60-70", "70-80", "80-90", "90-100+"],
#                 key='page_count',
#                 help="Estimated page range for the final ebook."
#             )
        
#         submitted = st.form_submit_button("Generate Ebook Skeleton", use_container_width=True, type="primary")

#     if submitted:
#         if not st.session_state.topic_input:
#             st.warning("Please provide main topics before generating the skeleton.")
#             return

#         st.session_state.stage_3_status = 'in_progress'
        
#         inputs = {
#             "compendio": st.session_state.compendio_md,
#             "projectBrief": st.session_state.project_brief_md,
#             "topicInput": st.session_state.topic_input,
#             "referenceCount": st.session_state.reference_count,
#             "MapeoContenido": json.dumps(st.session_state.mapping_combined),
#             "pageCount": st.session_state.page_count,
#             "subtemas": not st.session_state.subtemas_enabled # Inverted logic from doc
#         }
        
#         st.info("Generating the ebook skeleton... This might take a moment.")
#         stream_container = st.empty()
        
#         result = process_wordware_api(APP_IDS["theme_selector"], inputs, stream_container)
        
#         if result:
#             st.session_state.skeleton = result
#             # Extract chapter sequence for Stage 4 (count only main chapters)
#             try:
#                 estructura_capitulos = result.get('EsqueletoMaestro', {}).get('esqueletoLogica', {}).get('estructura_capitulos', [])
#                 # Simple counting - each item in the array is a chapter
#                 chapter_list = [f"capitulo_{i+1}" for i in range(len(estructura_capitulos))]
                
#                 st.session_state.chapter_sequence = chapter_list
#                 st.session_state.stage_3_status = 'completed'
#                 st.success("Stage 3 Completed! Ebook skeleton generated successfully.")
#             except Exception as e:
#                 st.session_state.stage_3_status = 'error'
#                 st.error(f"Could not parse chapter structure from skeleton: {e}")
#                 st.json(result)
#         else:
#             st.session_state.stage_3_status = 'error'
#             st.error("Failed to generate ebook skeleton.")
#         st.rerun()

#     if st.session_state.stage_3_status == 'completed':
#         st.success("✅ Stage 3 is complete. You can now proceed to Stage 4.")
        
#         # Initialize structured editor session state
#         if 'structured_chapters' not in st.session_state:
#             st.session_state.structured_chapters = []
#             st.session_state.structured_editor_initialized = False
        
#         esqueleto_maestro = st.session_state.skeleton.get('EsqueletoMaestro', {})
#         esqueleto_logica = esqueleto_maestro.get('esqueletoLogica', {})
        
#         with st.expander("View & Edit Ebook Skeleton", expanded=True):
#             # Initialize or refresh structured data when entering edit mode
#             def initialize_structured_data():
#                 estructura_capitulos = esqueleto_logica.get('estructura_capitulos', [])
#                 structured_chapters = []
                
#                 for item in estructura_capitulos:
#                     if isinstance(item, str):
#                         # Split by " | " to separate main chapter from subtopics
#                         parts = [part.strip() for part in item.split(' | ') if part.strip()]
#                         if parts:
#                             main_chapter = parts[0]
#                             subtopics = parts[1:] if len(parts) > 1 else []
#                             structured_chapters.append({
#                                 'title': main_chapter,
#                                 'subtopics': subtopics
#                             })
                
#                 st.session_state.structured_chapters = structured_chapters
#                 st.session_state.structured_editor_initialized = True
            
#             # Edit mode toggle
#             col1, col2 = st.columns([3, 1])
            
#             with col2:
#                 if 'skeleton_edit_mode' not in st.session_state:
#                     st.session_state.skeleton_edit_mode = False
                
#                 edit_button_label = "Save Changes" if st.session_state.skeleton_edit_mode else "Edit Structure"
#                 if st.button(edit_button_label, key="edit_skeleton_btn"):
#                     if st.session_state.skeleton_edit_mode:
#                         # Save mode - reconstruct the estructura_capitulos with pipe format
#                         new_estructura_capitulos = []
                        
#                         for chapter in st.session_state.structured_chapters:
#                             if chapter['title'].strip():  # Only add non-empty chapters
#                                 # Combine main chapter with subtopics using " | " separator
#                                 chapter_parts = [chapter['title']]
#                                 for subtopic in chapter['subtopics']:
#                                     if subtopic.strip():  # Only add non-empty subtopics
#                                         chapter_parts.append(subtopic)
                                
#                                 # Join with " | " format
#                                 chapter_string = ' | '.join(chapter_parts)
#                                 new_estructura_capitulos.append(chapter_string)
                        
#                         # Update the skeleton data
#                         st.session_state.skeleton['EsqueletoMaestro']['esqueletoLogica']['estructura_capitulos'] = new_estructura_capitulos
                        
#                         # Update narrative arc if edited
#                         edited_narrative = st.session_state.get("edit_narrative", esqueleto_logica.get('arco_narrativo', ''))
#                         st.session_state.skeleton['EsqueletoMaestro']['esqueletoLogica']['arco_narrativo'] = edited_narrative
                        
#                         # Update chapter sequence for Stage 4
#                         chapter_list = [f"capitulo_{i+1}" for i in range(len(new_estructura_capitulos))]
#                         st.session_state.chapter_sequence = chapter_list
                        
#                         # Exit edit mode
#                         st.session_state.skeleton_edit_mode = False
#                         st.success(f"Structure updated! {len(new_estructura_capitulos)} chapters defined.")
#                         st.rerun()
#                     else:
#                         # Enter edit mode - reinitialize with current data
#                         initialize_structured_data()
#                         st.session_state.skeleton_edit_mode = True
#                         st.rerun()
            
#             # Chapter Structure Section
#             st.markdown("#### Chapter Structure")
            
#             if st.session_state.skeleton_edit_mode:
#                 # Structured editor interface
#                 for i, chapter in enumerate(st.session_state.structured_chapters):
#                     with st.container():
#                         col1, col2, col3 = st.columns([6, 1, 1])
                        
#                         with col1:
#                             # Chapter title editor (main topic)
#                             new_title = st.text_input(
#                                 f"Chapter {i+1} Title:",
#                                 value=chapter['title'],
#                                 key=f"chapter_title_{i}"
#                             )
#                             st.session_state.structured_chapters[i]['title'] = new_title
                        
#                         with col2:
#                             # Add subtopic button
#                             if st.button("+ Sub", key=f"add_sub_{i}", help="Add Subtopic"):
#                                 st.session_state.structured_chapters[i]['subtopics'].append("")
#                                 st.rerun()
                        
#                         with col3:
#                             # Remove chapter button
#                             if len(st.session_state.structured_chapters) > 1:
#                                 if st.button("🗑️", key=f"del_chap_{i}", help="Delete Chapter"):
#                                     st.session_state.structured_chapters.pop(i)
#                                     st.rerun()
                        
#                         # Subtopics editor
#                         for j, subtopic in enumerate(chapter['subtopics']):
#                             col1, col2 = st.columns([8, 1])
                            
#                             with col1:
#                                 new_subtopic = st.text_input(
#                                     f"Subtopic {j+1}:",
#                                     value=subtopic,
#                                     key=f"subtopic_{i}_{j}",
#                                     label_visibility="collapsed"
#                                 )
#                                 st.session_state.structured_chapters[i]['subtopics'][j] = new_subtopic
                            
#                             with col2:
#                                 if st.button("🗑️", key=f"del_sub_{i}_{j}", help="Delete Subtopic"):
#                                     st.session_state.structured_chapters[i]['subtopics'].pop(j)
#                                     st.rerun()
                        
#                         st.markdown("---")
                
#                 # Add new chapter button
#                 if st.button("+ Add Chapter", key="add_chapter"):
#                     st.session_state.structured_chapters.append({
#                         'title': f"New Chapter {len(st.session_state.structured_chapters) + 1}",
#                         'subtopics': []
#                     })
#                     st.rerun()
            
#             else:
#                 # Display mode - show current structure with proper formatting
#                 chapters = esqueleto_logica.get('estructura_capitulos', [])
#                 for i, chapter_string in enumerate(chapters, 1):
#                     if isinstance(chapter_string, str):
#                         # Split by " | " to display main chapter and subtopics
#                         parts = [part.strip() for part in chapter_string.split(' | ') if part.strip()]
#                         if parts:
#                             # Main chapter
#                             st.markdown(f"**Chapter {i}: {parts[0]}**")
#                             # Subtopics
#                             for subtopic in parts[1:]:
#                                 st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;• {subtopic}")
            
#             # Narrative Arc Section
#             st.markdown("#### Narrative Arc")
#             if st.session_state.skeleton_edit_mode:
#                 st.text_area(
#                     "Edit narrative arc:",
#                     value=esqueleto_logica.get('arco_narrativo', ''),
#                     height=100,
#                     key="edit_narrative"
#                 )
#             else:
#                 st.write(esqueleto_logica.get('arco_narrativo', 'No narrative arc defined.'))
            
#             # Estimated Metrics (Read-only)
#             st.markdown("#### Estimated Metrics")
#             metricas = esqueleto_logica.get('metricas_estimadas', {})
#             col1, col2, col3 = st.columns(3)
#             with col1:
#                 st.metric("Total Words", metricas.get('palabras_totales', 'N/A'))
#             with col2:
#                 st.metric("Total Pages", metricas.get('paginas_totales', 'N/A'))
#             with col3:
#                 st.metric("Chapters", len(st.session_state.chapter_sequence))
            
#             # Reference Distribution (Collapsible, Read-only)
#             with st.expander("Reference Distribution"):
#                 ref_mapping = esqueleto_logica.get('distribuicion_referencias', {}).get('referenciasMapeo', [])
#                 if ref_mapping:
#                     for i, ref in enumerate(ref_mapping, 1):
#                         st.write(f"Chapter {i}: {ref}")
#                 else:
#                     st.write("No reference mapping available.")
        
#         st.info(f"The skeleton defines {len(st.session_state.chapter_sequence)} chapters to be generated.")

## --- Stage 4: Chapter Creation ---
def render_stage_4():
    st.header("Stage 4: Sequential Chapter Generation")
    st.markdown("Generate each chapter one by one. The context from the previously generated chapter is used to ensure narrative flow.")

    if not st.session_state.chapter_sequence:
        st.warning("No chapters defined in the skeleton from Stage 3.")
        return

    # Temporary fix for existing stored data with wrong structure
    if st.session_state.generated_chapters:
        for chapter_id, stored_data in list(st.session_state.generated_chapters.items()):
            if 'generatedChapter' in stored_data:
                # Fix the stored data structure
                chapter_title_data = stored_data.get('generatedChapter', {}).get('chapterTitle', {})
                if chapter_title_data:
                    st.session_state.generated_chapters[chapter_id] = chapter_title_data

    # Display progress
    total_chapters = len(st.session_state.chapter_sequence)
    completed_chapters = len(st.session_state.chapters_completed)
    st.progress(completed_chapters / total_chapters, text=f"{completed_chapters}/{total_chapters} Chapters Generated")

    if not st.session_state.book_complete:
        current_chapter_id = st.session_state.chapter_sequence[st.session_state.current_chapter_index]
        st.subheader(f"Next to Generate: `{current_chapter_id.replace('_', ' ').title()}`")

        if st.button(f"Generate {current_chapter_id.replace('_', ' ').title()}", type="primary"):
            st.session_state.stage_4_status = 'in_progress'
            
            inputs = {
                "Skeleton": json.dumps(st.session_state.skeleton.get('EsqueletoMaestro', {})),
                "CompendioMd": st.session_state.compendio_md,
                "previous_context": st.session_state.previous_context,
                "capituloConstruir": current_chapter_id
            }
            
            st.info(f"Generating content for {current_chapter_id}...")
            stream_container = st.empty()
            
            result = process_wordware_api(APP_IDS["chapter_creator"], inputs, stream_container)
            
            if result:
                # Extract the chapter data from the correct nested structure
                generated_chapter = result.get('generatedChapter', {})
                chapter_data = generated_chapter.get('chapterTitle', {})
                
                if chapter_data:
                    st.session_state.generated_chapters[current_chapter_id] = chapter_data
                    st.session_state.previous_context = chapter_data.get('resumen_para_siguiente', '')
                    st.session_state.chapters_completed.append(current_chapter_id)
                    st.session_state.current_chapter_index += 1
                    
                    st.toast(f"{current_chapter_id} generated successfully!", icon="🎉")

                    # Check for completion
                    if st.session_state.current_chapter_index >= total_chapters:
                        st.session_state.book_complete = True
                        st.session_state.stage_4_status = 'completed'
                        st.success("All chapters have been generated!")
                        st.balloons()
                else:
                    st.error(f"API response for {current_chapter_id} was malformed - no 'chapterTitle' data found.")
                    st.session_state.stage_4_status = 'error'
            else:
                st.error(f"Failed to generate chapter: {current_chapter_id}.")
                st.session_state.stage_4_status = 'error'
            st.rerun()
    else:
        st.success("✅ Stage 4 is complete. All chapters have been generated. Proceed to Stage 5 for final assembly.")

    # Display generated chapters
    if st.session_state.generated_chapters:
        st.divider()
        st.subheader("Generated Chapters Review")
        
        # Initialize edit mode tracking if not exists
        if 'edit_modes' not in st.session_state:
            st.session_state.edit_modes = {}
        
        for chapter_id, chapter_data in sorted(st.session_state.generated_chapters.items()):
            chapter_title = chapter_data.get('chapterTitle', chapter_id)
            is_edit_mode = st.session_state.edit_modes.get(chapter_id, False)
            
            with st.expander(f"📖 {chapter_title}"):
                col1, col2 = st.columns([3, 1])
                
                with col1:
                    st.metric("Word Count", chapter_data.get('conteo_palabras', 'N/A'))
                
                with col2:
                    edit_button_label = "Save Changes" if is_edit_mode else "Edit Chapter"
                    if st.button(edit_button_label, key=f"edit_btn_{chapter_id}"):
                        if is_edit_mode:
                            # Save mode - update session state with edited content
                            edited_content = st.session_state.get(f"edit_content_{chapter_id}", "")
                            edited_summary = st.session_state.get(f"edit_summary_{chapter_id}", "")
                            
                            # Update the chapter data
                            st.session_state.generated_chapters[chapter_id]['contenido_capitulo'] = edited_content
                            st.session_state.generated_chapters[chapter_id]['resumen_para_siguiente'] = edited_summary

                            if chapter_id == st.session_state.chapter_sequence[st.session_state.current_chapter_index - 1]:
                                st.session_state.previous_context = edited_summary
                            
                            # Recalculate word count
                            word_count = len(edited_content.split())
                            st.session_state.generated_chapters[chapter_id]['conteo_palabras'] = word_count
                            
                            # Exit edit mode
                            st.session_state.edit_modes[chapter_id] = False
                            st.rerun()
                        else:
                            # Enter edit mode
                            st.session_state.edit_modes[chapter_id] = True
                            st.rerun()
                
                st.markdown("#### Used References")
                st.write(chapter_data.get('referencias_usadas', []))
                
                st.markdown("#### Chapter Content")
                if is_edit_mode:
                    st.text_area(
                        "Edit chapter content:",
                        value=chapter_data.get('contenido_capitulo', ''),
                        height=400,
                        key=f"edit_content_{chapter_id}"
                    )
                else:
                    st.markdown(chapter_data.get('contenido_capitulo', 'No content found.'))
                
                st.markdown("---")
                st.markdown("**Summary for next chapter:**")
                if is_edit_mode:
                    st.text_area(
                        "Edit summary for next chapter:",
                        value=chapter_data.get('resumen_para_siguiente', ''),
                        height=100,
                        key=f"edit_summary_{chapter_id}"
                    )
                else:
                    st.write(chapter_data.get('resumen_para_siguiente', 'N/A'))




## --- Stage 5: Final Assembly ---
# def render_stage_5():
#     st.header("Stage 5: Final Ebook Assembly")
#     st.markdown("This final stage will assemble all generated chapters, create a table of contents, and produce the complete ebook in Markdown format.")

#     if not st.session_state.book_complete:
#         st.warning("Please complete all chapter generations in Stage 4 before proceeding.")
#         return
#     st.json(st.session_state.skeleton)  # See the actual structure


#     if st.button("Assemble Final Ebook", type="primary"):
#         st.session_state.stage_5_status = 'in_progress'
        
#         # The API is documented to pull from Google Sheets, abstracting the input.
#         # We will assume it may need the skeleton for structure. If not, this can be empty.
#         all_chapters_content = "\n\n---\n\n".join(
#             [ch.get('contenido_capitulo', '') for id, ch in sorted(st.session_state.generated_chapters.items())]
#         )
        
#         # A more robust implementation would pass chapter data, but we follow the docs.
#         # As the API pulls from a sheet, it might not need any input. Let's assume an empty input for now.
#         # Note: A real implementation might need to pass `skeleton` or chapter IDs.
#         inputs = {
#             "GeneratedEbook": all_chapters_content,
#             # "EsqueletoMaestro": json.dumps(st.session_state.skeleton)
#             "EsqueletoMaestro": json.dumps(st.session_state.skeleton.get('EsqueletoMaestro', {}))
#         }

#         st.info("Assembling the final ebook... This may take a moment.")
#         stream_container = st.empty()
#         result = process_wordware_api(APP_IDS["table_generator"], inputs, stream_container)


        
#         # if result:
#         #     st.session_state.final_ebook = result
#         #     st.session_state.stage_5_status = 'completed'
#         #     st.success("🎉 Ebook Generation Complete! 🎉")
#         #     st.balloons()
#         # else:
#         #     st.session_state.stage_5_status = 'error'
#         #     st.error("Failed to assemble the final ebook.")
#         # st.rerun()

#         if result:
#             # Convert dict to string only for Stage 5
#             if isinstance(result, dict):
#                 st.session_state.final_ebook = list(result.values())[0]
#             else:
#                 st.session_state.final_ebook = result
            
#             st.session_state.stage_5_status = 'completed'
#             st.success("🎉 Ebook Generation Complete! 🎉")
#             st.balloons()

#     if st.session_state.stage_5_status == 'completed':
#         st.success("✅ The final ebook has been generated successfully!")
#         st.download_button(
#             label="Download Final Ebook.md",
#             data=st.session_state.final_ebook.encode('utf-8'),
#             file_name="complete_ebook.md",
#             mime="text/markdown",
#             use_container_width=True
#         )
#         with st.expander("Preview Final Ebook", expanded=True):
#             st.markdown(st.session_state.final_ebook)
# def render_stage_5():
#     st.header("Stage 5: Final Ebook Assembly")
#     st.markdown("This final stage will assemble all generated chapters, create a table of contents, and produce the complete ebook in Markdown format.")

#     if not st.session_state.book_complete:
#         st.warning("Please complete all chapter generations in Stage 4 before proceeding.")
#         return

#     if st.button("Assemble Final Ebook", type="primary"):
#         st.session_state.stage_5_status = 'in_progress'
        
#         all_chapters_content = "\n\n---\n\n".join(
#             [ch.get('contenido_capitulo', '') for id, ch in sorted(st.session_state.generated_chapters.items())]
#         )
        
#         inputs = {
#             "GeneratedEbook": all_chapters_content,
#             "EsqueletoMaestro": json.dumps(st.session_state.skeleton.get('EsqueletoMaestro', {}))
#         }

#         st.info("Assembling the final ebook... This may take a moment.")
#         stream_container = st.empty()
#         result = process_wordware_api(APP_IDS["table_generator"], inputs, stream_container)

#         if result:
#             st.write("DEBUG: result type =", type(result))
#             st.write("DEBUG: result keys =", result.keys() if isinstance(result, dict) else "Not a dict")
#             if isinstance(result, dict):
#                 st.write("DEBUG: result content =", result)
            
#             # Handle non-structured generation response - FIXED VERSION
#             if isinstance(result, dict):
#                 # Get the first string value from the dictionary, regardless of structure
#                 for key, value in result.items():
#                     if isinstance(value, str):
#                         st.session_state.final_ebook = value
#                         break
#                 else:
#                     # If no string values found, convert entire dict to string
#                     st.session_state.final_ebook = str(result)
#             else:
#                 st.session_state.final_ebook = result
            
#             st.write("DEBUG: final_ebook stored as type =", type(st.session_state.final_ebook))
            
#             st.session_state.stage_5_status = 'completed'
#             st.success("🎉 Ebook Generation Complete! 🎉")
#             st.balloons()
#         else:
#             st.session_state.stage_5_status = 'error'
#             st.error("Failed to assemble the final ebook.")
#         st.rerun()

#     if st.session_state.stage_5_status == 'completed':
#         st.write("DEBUG: final_ebook type =", type(st.session_state.final_ebook))
#         st.write("DEBUG: final_ebook content =", st.session_state.final_ebook if isinstance(st.session_state.final_ebook, str) else "DICT DETECTED")
        
#         st.success("✅ The final ebook has been generated successfully!")
#         st.download_button(
#             label="Download Final Ebook.md",
#             data=st.session_state.final_ebook.encode('utf-8'),
#             file_name="complete_ebook.md",
#             mime="text/markdown",
#             use_container_width=True
#         )
#         with st.expander("Preview Final Ebook", expanded=True):
#             st.markdown(st.session_state.final_ebook)

def render_stage_5():
    st.header("Stage 5: Final Ebook Assembly")
    st.markdown("This final stage will assemble all generated chapters, create a table of contents, and produce the complete ebook in Markdown format.")

    if not st.session_state.book_complete:
        st.warning("Please complete all chapter generations in Stage 4 before proceeding.")
        return

    if st.button("Assemble Final Ebook", type="primary"):
        st.session_state.stage_5_status = 'in_progress'
        
        all_chapters_content = "\n\n---\n\n".join(
            [ch.get('contenido_capitulo', '') for id, ch in sorted(st.session_state.generated_chapters.items())]
        )
        
        inputs = {
            "GeneratedEbook": all_chapters_content,
            "EsqueletoMaestro": json.dumps(st.session_state.skeleton.get('EsqueletoMaestro', {}))
        }

        st.info("Assembling the final ebook... This may take a moment.")
        stream_container = st.empty()
        result = process_wordware_api(APP_IDS["table_generator"], inputs, stream_container)

        if result:
            # Handle non-structured generation response
            if isinstance(result, dict):
                # Get the first string value from the dictionary
                for key, value in result.items():
                    if isinstance(value, str):
                        st.session_state.final_ebook = value
                        break
                else:
                    # If no string values found, convert entire dict to string
                    st.session_state.final_ebook = str(result)
            else:
                st.session_state.final_ebook = result
            
            st.session_state.stage_5_status = 'completed'
            st.success("🎉 Ebook Generation Complete! 🎉")
            st.balloons()
        else:
            st.session_state.stage_5_status = 'error'
            st.error("Failed to assemble the final ebook.")
        st.rerun()

    if st.session_state.stage_5_status == 'completed':
        st.success("✅ The final ebook has been generated successfully!")
        st.download_button(
            label="Download Final Ebook.md",
            data=st.session_state.final_ebook.encode('utf-8'),
            file_name="complete_ebook.md",
            mime="text/markdown",
            use_container_width=True
        )
        with st.expander("Preview Final Ebook", expanded=True):
            st.markdown(st.session_state.final_ebook)

# --- MAIN APPLICATION LOGIC ---

def main():
    # """Main function to run the Streamlit app."""
    # st.title("Wordware Ebook Generation Pipeline")
    
    # Password protection - ADD THESE 3 LINES
    if not check_password():
        st.stop()
    
    st.title("Wordware Ebook Generation Pipeline")
    st.markdown("Follow the stages in the sidebar to transform your source documents into a complete ebook.")

    initialize_session_state()
    render_sidebar()
    render_progress_indicator()

    # Main content area based on the current stage
    if st.session_state.current_stage == 1:
        render_stage_1()
    elif st.session_state.current_stage == 2:
        render_stage_2()
    elif st.session_state.current_stage == 3:
        render_stage_3()
    elif st.session_state.current_stage == 4:
        render_stage_4()
    elif st.session_state.current_stage == 5:
        render_stage_5()

if __name__ == "__main__":
    main()
