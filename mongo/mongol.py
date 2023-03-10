#! /usr/bin/env python3
#
# Copyright (c) 2014-2023 Intel Corporation
#
# SPDX-License-Identifier: Apache-2.0

import ssl

def arg_parse_add(arg_parser):
    arg_parser.add_argument("--mongo-url", action = "store",
                            default = "http://localhost:7061/database",
                            help = "URL to Mongo database server "
                            "[%(default)s]")
    arg_parser.add_argument("--mongo-db", action = "store",
                            default = "DBNAME",
                            help = "Name of database in Mongo server "
                            "[%(default)s]")
    arg_parser.add_argument("--collection-id", action = "store", type = str,
                            default = 'tcf-v0.11-branch-zephyr-master',
                            help = "Default collection to use [%(default)s]")
    arg_parser.add_argument("--summary-collection-id", action = "store",
                            type = str, default = None,
                            help = "Default collection to use (defaults "
                            "to COLLECTION-ID_summary_per_run")
    arg_parser.add_argument("--mongo-cert", action = "store",
                            default = None,
                            help = "Pointer to certificate file bundle "
                            "[%(default)s]")
    arg_parser.add_argument("--no-mongo-cert-verification",
                            action = "store_false",
                            dest = "mongo_cert_verification",
                            default = False,
                            help = "Don't verificate mongo certificates"
                            " [default]")
    arg_parser.add_argument("--mongo-cert-verification",
                            action = "store_true",
                            dest = "mongo_cert_verification",
                            default = True,
                            help = "Verificate mongo certificates")
    arg_parser.set_defaults(mongo_cert_verification = False)

def args_chew(args, extra_params):
    if args.mongo_cert:
        #extra_params["ssl_keyfile"] = args.mongo_cert
        #extra_params["ssl_certfile"] = args.mongo_cert
        extra_params["ssl_ca_certs"] = args.mongo_cert
        if not args.mongo_cert_verification:
            extra_params["ssl_cert_reqs"] = ssl.CERT_NONE
    if not args.summary_collection_id:
        args.summary_collection_id = args.collection_id + "_summary_per_run"
