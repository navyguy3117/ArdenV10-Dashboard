
import requests
import json
import time

archive_path = '/home/mikegg/.openclaw/workspace/imports/chat-archives/6cf22a6dd0f7b1f14c3678a4a3625e469a545aca871651f45425bd105d50514b-2026-02-17-00-42-25-7412e7141c2b4677ac6b1f0dc86dd871/conversations.json'
api_url = 'http://10.10.10.98:1234/api/v1/chat'
output_path = '/home/mikegg/.openclaw/workspace/memory/archive-summaries/profile-from-gpt-2026-02-23.md'
model_name = 'qwen2.5-14b-instruct'
configured_context_length = 4096

def extract_text_from_conversation_entry(entry):
    """Extracts clean text content from a single conversation entry."""
    extracted_content = ""
    # Primary structure: message with content
    if 'message' in entry and entry['message'] and 'content' in entry['message']:
        content = entry['message']['content']
        if content and isinstance(content, str) and len(content.strip()) > 10: # Basic check for meaningful content
            extracted_content += content.strip() + "\n"
    # Secondary structure: mapping which might contain messages
    elif 'mapping' in entry:
        for key, value in entry['mapping'].items():
            if 'message' in value and value['message'] and 'content' in value['message']:
                content = value['message']['content']
                if content and isinstance(content, str) and len(content.strip()) > 10:
                    extracted_content += content.strip() + "\n"
    return extracted_content

def process_chat_log_in_chunks(archive_path, api_url, output_path, model_name, context_length, temperature=0.3):
    """Processes chat log entries in chunks by extracting text and sending to LM Studio."""
    
    try:
        with open(archive_path, 'r', encoding='utf-8') as f:
            all_data = json.load(f)
        
        # Initialize/overwrite the output file
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# Mike (Beanz) Profile - Digested Archive\n\n")
            f.write("## Comprehensive Profile Summary\n\n")
            f.write(f"Processing {len(all_data)} individual conversation entries.\n\n")
            f.write("Date: 2026-02-23\n\n")

        aggregated_summary = ""
        processed_count = 0
        
        print(f"Starting digestion of {len(all_data)} conversation entries with model: {model_name}")

        for i, entry in enumerate(all_data):
            entry_text = extract_text_from_conversation_entry(entry)
            
            if not entry_text: # Skip if no meaningful text extracted
                print(f"Skipping entry {i+1} - no significant text found.")
                continue

            # Construct prompt for LM Studio
            prompt_content = (
                f"Analyze this chat entry and extract key details about Mike (Beanz) regarding his technical setup, preferences, working style, or interests. "
                f"Be extremely concise. If nothing significant is found in this entry, reply 'NO SIGNIFICANT DETAILS FOUND'. Append to the existing profile summary.\n\n"
                f"Existing Profile Summary:\n'''\n{aggregated_summary}\n'''\n\n"
                f"Chat Entry Text:\n'''\n{entry_text}\n'''"
            )

            # Token limit for the prompt construction. This needs to be dynamically managed.
            # For now, assume each text chunk is small enough.
            # If errors persist, we will need a token counter.
            
            payload = {
                "model": model_name,
                "input": [{"type": "text", "content": prompt_content}], 
                "system_prompt": "You are Arden's memory processor. Extract key profile points about Mike. Be very concise or say nothing if no significant details are found.",
                "context_length": context_length, 
                "temperature": 0.1 # Lower temperature for factual extraction
            }

            print(f"Processing entry {i+1}/{len(all_data)}...")
            
            try:
                response = requests.post(api_url, json=payload, timeout=120) 

                if response.status_code == 200:
                    result_data = response.json()
                    if 'output' in result_data and result_data['output']:
                        for output_item in result_data['output']:
                            if output_item['type'] == 'message':
                                current_entry_summary = output_item['content'].strip()
                                if current_entry_summary and "NO SIGNIFICANT DETAILS FOUND" not in current_entry_summary.upper():
                                    aggregated_summary += current_entry_summary + "\n"
                                    print(f"Entry {i+1} summary added.")
                                else:
                                    print(f"Entry {i+1} - No significant content found.")
                            else:
                                print(f"Unexpected output type for entry {i+1}: {output_item.get('type')}")
                    else:
                        print(f"Warning: No 'output' found in response for entry {i+1}.")
                else:
                    print(f"LM_STUDIO_ERROR for entry {i+1}: {response.status_code} - {response.text}")
                    # In case of errors, we might want to pause or retry logic here.
                    # For now, we'll just continue to the next entry if possible.
                    # break # If errors are persistent, might need to break loop

            except requests.exceptions.RequestException as e:
                print(f"ERROR: Connection to LM Studio failed for entry {i+1}: {e}")
                # If connection fails, it might be better to stop entirely.
                break 
            except Exception as e:
                print(f"An unexpected error occurred processing entry {i+1}: {str(e)}")
                continue 
            
            processed_count += 1
            # Periodic saves to the file so progress isn't lost
            if processed_count % 10 == 0:
                with open(output_path, 'a', encoding='utf-8') as f: # Append to the file
                    f.write(f"\n### Progress Update (Entry {i+1})\n\n{aggregated_summary}\n")
                print(f"Saved progress after entry {i+1}.")

            time.sleep(2) # Small delay between requests

        # Final write of the complete summary
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write("# Mike (Beanz) Profile - Digested Archive\n\n")
            f.write("## Comprehensive Profile Summary\n\n")
            f.write(aggregated_summary)
            f.write("\n---\nEnd of digestion process.\n")
        
        print("DIGESTION_COMPLETE")

    except Exception as e:
        print(f"An error occurred during initial setup: {str(e)}")

