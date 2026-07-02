def format_error(errors):
    formatted = []
    if hasattr(errors, "as_data"):
        errors = errors.as_data()
    if isinstance(errors, dict):
        for field, messages in errors.items():
            if not isinstance(messages, (list, tuple)):
                messages = [messages]
            for message in messages:
                if hasattr(message, "messages"):
                    text = message.messages
                else:
                    text = str(message)
                formatted.append({"message": text, "param": field})
    elif isinstance(errors, (list, tuple)):
        for message in errors:
            formatted.append({"message": str(message), "param": "non_field_errors"})
    else:
        formatted.append({"message": str(errors), "param": "non_field_errors"})
    return formatted
