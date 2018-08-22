#
# TCF configuration for local host ttbd server
#
# This allows access to the ttbd server running in the local host#

import tcfl.config

tcfl.config.url_add('https://localhost:5000', ssl_ignore = True, aka = 'local')
