"""Thin launcher for the English Quest HTTP server."""

from http.server import ThreadingHTTPServer
import argparse
import webbrowser

from english_overlap.database import migrate_database
from english_overlap.app import HOST, PORT, API_KEY
from english_overlap.http import Handler, schedule_automatic_difficulty


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Start English Quest on this computer.')
    parser.add_argument('--open-browser', action='store_true', help='Open the app when the server is ready.')
    args = parser.parse_args()
    version, backup_path = migrate_database()
    print(f'Database schema version: {version}')
    if backup_path:
        print(f'Pre-migration backup: {backup_path}')
    print(f'English Quest: http://{HOST}:{PORT}')
    print('API key:', 'configured' if API_KEY else 'NOT CONFIGURED')
    auto_job=schedule_automatic_difficulty()
    if auto_job:
        print(f'Automatic CEFR assessment job: {auto_job}')
    with ThreadingHTTPServer((HOST, PORT), Handler) as server:
        if args.open_browser:
            webbrowser.open(f'http://{HOST}:{PORT}')
        server.serve_forever()
