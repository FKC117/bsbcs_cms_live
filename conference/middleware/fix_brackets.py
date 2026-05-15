import re

class SquareBracketMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        
        # Only process HTML responses
        if response.has_header('Content-Type') and 'text/html' in response['Content-Type']:
            try:
                content = response.content.decode('utf-8')
                
                # Check if rogue brackets exist
                if '[]' in content:
                    # Refined logic: strip ALL [] that are not inside <script> or <style> tags.
                    # This protects JS/CSS arrays/syntax while aggressively cleaning rogue brackets.
                    # 1. Split content using a regex that captures <script> or <style> tags (to preserve them)
                    parts = re.split(r'(<(?:script|style).*?>.*?</(?:script|style)>)', content, flags=re.DOTALL | re.IGNORECASE)
                    
                    new_parts = []
                    for part in parts:
                        lowered = part.lower()
                        if lowered.startswith('<script') or lowered.startswith('<style'):
                            # Preserve script and style content exactly
                            new_parts.append(part)
                        else:
                            # In all other parts of the HTML (text and attributes),
                            # we search for and remove any literal "[]".
                            new_parts.append(part.replace('[]', ''))
                    
                    new_content = "".join(new_parts)
                    
                    response.content = new_content.encode('utf-8')
                    # Update Content-Length header if we changed the content
                    if response.has_header('Content-Length'):
                        response['Content-Length'] = str(len(response.content))
            except Exception:
                # Fallback: if decoding fails, just return original response
                pass
                
        return response
