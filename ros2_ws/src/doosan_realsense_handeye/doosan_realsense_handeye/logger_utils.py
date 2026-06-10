def safe_log_info(logger, message):
    if hasattr(logger, "info"):
        logger.info(message)
    elif hasattr(logger, "dinfo"):
        logger.dinfo(message)
    else:
        logger.warn(message)

