#!/usr/bin/env python3
import tldextract
import boto3
import sys
import datetime
import argparse
from typing import Tuple
from botocore.exceptions import ClientError, NoRegionError


class FireProx(object):
    def __init__(self, arguments: argparse.Namespace, help_text: str):
        self.profile_name = arguments.profile_name
        self.access_key = arguments.access_key
        self.secret_access_key = arguments.secret_access_key
        self.session_token = arguments.session_token
        self.region = arguments.region
        self.command = arguments.command
        self.api_id = arguments.api_id
        self.url = arguments.url
        self.api_list = []
        self.client = None
        self.session = None
        self.help = help_text

        if self.access_key and self.secret_access_key:
            if not self.region:
                self.error('Please provide a region with AWS credentials')

        if not self.load_creds():
            self.error('Unable to load AWS credentials')

    def __str__(self):
        return 'FireProx()'

    def _try_instance_profile(self) -> bool:
        """Try instance profile credentials

        :return:
        """
        try:
            if not self.region:
                self.client = boto3.client('apigateway')
            else:
                self.client = boto3.client(
                    'apigateway',
                    region_name=self.region
                )
            self.client.get_account()
            self.region = self.client._client_config.region_name
            return True
        except:
            return False

    def load_creds(self) -> bool:
        """Load credentials from AWS config and credentials files if present.

        :return:
        """
        # If no access_key, secret_key, or profile name provided, try instance credentials
        if not any([self.access_key, self.secret_access_key, self.profile_name]):
            return self._try_instance_profile()

        if self.profile_name:
            session_details = { 'profile_name': self.profile_name }
        elif self.access_key and self.secret_access_key:
            session_details = {
                'aws_access_key_id': self.access_key,
                'aws_secret_access_key': self.secret_access_key
            }
            if self.session_token:
                session_details['aws_sessoin_token'] = self.session_token
        else:
            self.error('Please configure a profile or provice access keys')
            return False
        
        # Test provided access keys or profile
        try:
            session_details['region_name'] = self.region
            self.session = boto3.session.Session(**session_details)
            self.client = self.session.client('apigateway')
            self.region = self.session.region_name
            return True
        except ClientError as error:
            self.error(error)
        except NoRegionError as error:
            self.error(error)
        return False


    def error(self, error):
        print(self.help)
        sys.exit(error)

    def get_template(self):
        url = self.url
        if url[-1] == '/':
            url = url[:-1]

        title = 'fireprox_{}'.format(
            tldextract.extract(url).domain
        )
        version_date = f'{datetime.datetime.now():%Y-%m-%dT%XZ}'
        template = '''
        {
          "swagger": "2.0",
          "info": {
            "version": "{{version_date}}",
            "title": "{{title}}"
          },
          "basePath": "/",
          "schemes": [
            "https"
          ],
          "paths": {
            "/": {
              "get": {
                "parameters": [
                  {
                    "name": "proxy",
                    "in": "path",
                    "required": true,
                    "type": "string"
                  },
                  {
                    "name": "X-My-X-Forwarded-For",
                    "in": "header",
                    "required": false,
                    "type": "string"
                  }
                ],
                "responses": {},
                "x-amazon-apigateway-integration": {
                  "uri": "{{url}}/",
                  "responses": {
                    "default": {
                      "statusCode": "200"
                    }
                  },
                  "requestParameters": {
                    "integration.request.path.proxy": "method.request.path.proxy",
                    "integration.request.header.X-Forwarded-For": "method.request.header.X-My-X-Forwarded-For"
                  },
                  "passthroughBehavior": "when_no_match",
                  "httpMethod": "ANY",
                  "cacheNamespace": "irx7tm",
                  "cacheKeyParameters": [
                    "method.request.path.proxy"
                  ],
                  "type": "http_proxy"
                }
              }
            },
            "/{proxy+}": {
              "x-amazon-apigateway-any-method": {
                "produces": [
                  "application/json"
                ],
                "parameters": [
                  {
                    "name": "proxy",
                    "in": "path",
                    "required": true,
                    "type": "string"
                  },
                  {
                    "name": "X-My-X-Forwarded-For",
                    "in": "header",
                    "required": false,
                    "type": "string"
                  }
                ],
                "responses": {},
                "x-amazon-apigateway-integration": {
                  "uri": "{{url}}/{proxy}",
                  "responses": {
                    "default": {
                      "statusCode": "200"
                    }
                  },
                  "requestParameters": {
                    "integration.request.path.proxy": "method.request.path.proxy",
                    "integration.request.header.X-Forwarded-For": "method.request.header.X-My-X-Forwarded-For"
                  },
                  "passthroughBehavior": "when_no_match",
                  "httpMethod": "ANY",
                  "cacheNamespace": "irx7tm",
                  "cacheKeyParameters": [
                    "method.request.path.proxy"
                  ],
                  "type": "http_proxy"
                }
              }
            }
          }
        }
        '''
        template = template.replace('{{url}}', url)
        template = template.replace('{{title}}', title)
        template = template.replace('{{version_date}}', version_date)

        return str.encode(template)

    def create_api(self, url):
        if not url:
            self.error('Please provide a valid URL end-point')

        print(f'Creating => {url}...')

        template = self.get_template()
        try:
            response = self.client.import_rest_api(
                parameters={
                    'endpointConfigurationTypes': 'REGIONAL'
                },
                body=template
            )
        except ClientError as error: 
            self.error(error)
        resource_id, proxy_url = self.create_deployment(response['id'])
        self.store_api(
            response['id'],
            response['name'],
            response['createdDate'],
            response['version'],
            url,
            resource_id,
            proxy_url
        )

    def update_api(self, api_id, url):
        if not any([api_id, url]):
            self.error('Please provide a valid API ID and URL end-point')

        if url[-1] == '/':
            url = url[:-1]

        resource_id = self.get_resource(api_id)
        if resource_id:
            print(f'Found resource {resource_id} for {api_id}!')
            try:
                response = self.client.update_integration(
                    restApiId=api_id,
                    resourceId=resource_id,
                    httpMethod='ANY',
                    patchOperations=[
                        {
                            'op': 'replace',
                            'path': '/uri',
                            'value': '{}/{}'.format(url, r'{proxy}'),
                        },
                    ]
                )
            except ClientError as error: 
                self.error(error)
            return response['uri'].replace('/{proxy}', '') == url
        else:
            self.error(f'Unable to update, no valid resource for {api_id}')

    def delete_api(self, api_id):
        if not api_id:
            self.error('Please provide a valid API ID')
        items = self.list_api(api_id)
        for item in items:
            item_api_id = item['id']
            if item_api_id == api_id:
                try:
                    self.client.delete_rest_api(
                        restApiId=api_id
                    )
                except ClientError as error: 
                    self.error(error)
                return True
        return False

    def list_api(self, deleted_api_id=None):
        try:
            response = self.client.get_rest_apis()
        except ClientError as error: 
            self.error(error)
        for item in response['items']:
            try:
                created_dt = item['createdDate']
                api_id = item['id']
                name = item['name']
                proxy_url = self.get_integration(api_id).replace('{proxy}', '')
                url = f'https://{api_id}.execute-api.{self.region}.amazonaws.com/fireprox/'
                if not api_id == deleted_api_id:
                    print(f'[{created_dt}] ({api_id}) {name}: {url} => {proxy_url}')
            except:
                pass

        return response['items']

    def store_api(self, api_id, name, created_dt, version_dt, url,
                  resource_id, proxy_url):
        print(
            f'[{created_dt}] ({api_id}) {name} => {proxy_url} ({url})'
        )

    def create_deployment(self, api_id):
        if not api_id:
            self.error('Please provide a valid API ID')

        try:
            response = self.client.create_deployment(
                restApiId=api_id,
                stageName='fireprox',
                stageDescription='FireProx Prod',
                description='FireProx Production Deployment'
            )
        except ClientError as error: 
            self.error(error)
        resource_id = response['id']
        return (resource_id,
                f'https://{api_id}.execute-api.{self.region}.amazonaws.com/fireprox/')

    def get_resource(self, api_id):
        if not api_id:
            self.error('Please provide a valid API ID')
        try:
            response = self.client.get_resources(restApiId=api_id)
        except ClientError as error: 
            self.error(error)
        items = response['items']
        for item in items:
            item_id = item['id']
            item_path = item['path']
            if item_path == '/{proxy+}':
                return item_id
        return None

    def get_integration(self, api_id):
        if not api_id:
            self.error('Please provide a valid API ID')
        resource_id = self.get_resource(api_id)
        try:
            response = self.client.get_integration(
                restApiId=api_id,
                resourceId=resource_id,
                httpMethod='ANY'
            )
        except ClientError as error: 
            self.error(error)
        return response['uri']


def parse_arguments() -> Tuple[argparse.Namespace, str]:
    """Parse command line arguments and return namespace

    :return: Namespace for arguments and help text as a tuple
    """
    parser = argparse.ArgumentParser(description='FireProx API Gateway Manager')
    parser.add_argument('-p', '--profile_name',
                        help='AWS Profile Name to retrieve credentials', type=str, default=None)
    parser.add_argument('-a', '--access_key',
                        help='AWS Access Key', type=str, default=None)
    parser.add_argument('-s', '--secret_access_key',
                        help='AWS Secret Access Key', type=str, default=None)
    parser.add_argument('-t', '--session_token',
                        help='AWS Session Token', type=str, default=None)
    parser.add_argument('-r', '--region',
                        help='AWS Region', type=str, default='us-east-1')
    parser.add_argument('-c', '--command',
                        help='Commands: list, create, delete, update', type=str, default='list')
    parser.add_argument('-i', '--api_id',
                        help='API ID', type=str, required=False)
    parser.add_argument('-u', '--url',
                        help='URL end-point', type=str, required=False)
    return parser.parse_args(), parser.format_help()


def main():
    """Run the main program

    :return:
    """
    args, help_text = parse_arguments()
    fp = FireProx(args, help_text)
    if args.command == 'list':
        print(f'Listing {args.region} API\'s...')
        result = fp.list_api()

    elif args.command == 'create':
        result = fp.create_api(fp.url)

    elif args.command == 'delete':
        result = fp.delete_api(fp.api_id)
        success = 'Success!' if result else 'Failed!'
        print(f'Deleting {fp.api_id} => {success}')

    elif args.command == 'update':
        print(f'Updating {fp.api_id} => {fp.url}...')
        result = fp.update_api(fp.api_id, fp.url)
        success = 'Success!' if result else 'Failed!'
        print(f'API Update Complete: {success}')

    else:
        print(f'[ERROR] Unsupported command: {args.command}\n')
        print(help_text)
        sys.exit(1)


if __name__ == '__main__':
    main()
