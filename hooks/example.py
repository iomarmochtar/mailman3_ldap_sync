
def main(conf, instance, data):
    """
    Example of hook file

    conf: <dict> hook configuration in config.ini
    logger: <object> instance logger that used in main script
    data: <dict> cleaned result data based on ldap query
    """
    instance.logger.debug("inside example hook")
