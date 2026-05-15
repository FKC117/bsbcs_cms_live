"""Temporary debug middleware to detect when templates receive an `event`
variable that is a class or not a model instance.

This middleware monkey-patches django.template.Template.render to inspect
contexts before rendering. It logs cases where context['event'] appears to
be a class or doesn't look like a model instance (no `id` attribute).
"""

import logging
import traceback

try:
    from django.db.models import Model
    HAS_DJANGO = True
except Exception:
    Model = object
    HAS_DJANGO = False

logger = logging.getLogger('debug_event')


def _inspect_context_event(context):
    """Check if context has a suspicious `event` variable and log it."""
    try:
        if 'event' in context:
            event = context['event']
            
            is_class = isinstance(event, type)
            is_model_instance = isinstance(event, Model)
            has_id = hasattr(event, 'id')
            
            if is_class or (not is_model_instance and not has_id):
                logger.warning(
                    "DEBUG_EVENT: event_type=%s event_repr=%r has_id=%s is_model_instance=%s",
                    type(event),
                    event,
                    has_id,
                    is_model_instance,
                )
                return True
    except Exception:
        logger.exception('Error in _inspect_context_event')
    return False


class DebugEventMiddleware:
    """Temporary middleware to detect when templates receive a bad `event`.

    This wraps django.template.Template.render via monkey-patching to
    inspect contexts before rendering. It logs cases where context['event']
    appears to be a class or doesn't look like a model instance (no `id`
    attribute). Add this middleware to MIDDLEWARE while debugging and
    remove it afterwards.
    """

    def __init__(self, get_response):
        self.get_response = get_response
        # Monkey-patch Django's Template.render to inspect contexts
        if HAS_DJANGO:
            self._patch_template_render()

    def __call__(self, request):
        return self.get_response(request)
    
    def _patch_template_render(self):
        """Monkey-patch django.template.Template.render to inspect contexts."""
        try:
            from django.template import Template
            original_render = Template.render

            def patched_render(self_tmpl, context=None, *args, **kwargs):
                # Try to obtain a plain dict from the provided context
                try:
                    ctx_dict = {}
                    if context is None:
                        ctx_dict = {}
                    else:
                        # Django Context has a flatten() method in newer versions
                        if hasattr(context, 'flatten'):
                            try:
                                ctx_dict = context.flatten()
                            except Exception:
                                # fallback to mapping conversion
                                try:
                                    ctx_dict = dict(context)
                                except Exception:
                                    ctx_dict = {}
                        elif isinstance(context, dict):
                            ctx_dict = context
                        else:
                            try:
                                ctx_dict = dict(context)
                            except Exception:
                                ctx_dict = {}

                    # Inspect context before rendering; capture template name and request path if available
                    tmpl_name = getattr(self_tmpl, 'name', None)
                    request_obj = ctx_dict.get('request') if isinstance(ctx_dict, dict) else None
                    path = getattr(request_obj, 'path', None)
                    found = _inspect_context_event(ctx_dict)
                    if found:
                        stack = ''.join(traceback.format_stack(limit=10))
                        logger.warning("DEBUG_EVENT_CONTEXT: path=%s template=%s", path, tmpl_name)
                        logger.warning("DEBUG_EVENT_STACK:\n%s", stack)
                except Exception:
                    logger.exception('DebugEventMiddleware: error inspecting context')

                # Call the original render implementation with all args
                return original_render(self_tmpl, context, *args, **kwargs)  # type: ignore[arg-type]

            Template.render = patched_render  # type: ignore[assignment]
            logger.info("DebugEventMiddleware: patched Template.render")
        except Exception:
            logger.exception('DebugEventMiddleware: failed to patch Template.render')
