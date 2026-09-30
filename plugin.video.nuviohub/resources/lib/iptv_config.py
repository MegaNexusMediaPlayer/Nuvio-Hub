"""A dedicated IPTV Simple instance; other playlists and credentials are preserved."""
from pathlib import Path
import os
import time
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit,urlencode

def valid_url(value):
    p=urlsplit(value.strip())
    if p.scheme not in ('http','https') or not p.netloc or any(c in value for c in ('\r','\n')):
        raise ValueError('Enter a complete HTTP or HTTPS URL.')
    return value.strip()

def xtream_urls(server,username,password):
    server=valid_url(server).rstrip('/')
    if urlsplit(server).query or urlsplit(server).fragment:raise ValueError('Enter the server address and port, without a query.')
    if not username or not password:raise ValueError('Username and password are required.')
    query=urlencode({'username':username,'password':password})
    return server+'/get.php?'+query+'&type=m3u_plus&output=ts',server+'/xmltv.php?'+query

def write_instance(profile,m3u,epg,instance_id=None):
    m3u=valid_url(m3u);epg=valid_url(epg) if epg else ''
    profile=Path(profile);profile.mkdir(parents=True,exist_ok=True)
    iid=int(instance_id or 90100)
    while (profile/f'instance-settings-{iid}.xml').exists():
        old=ET.parse(profile/f'instance-settings-{iid}.xml').getroot()
        name=old.find("setting[@id='kodi_addon_instance_name']")
        if name is not None and name.text=='Nuvio IPTV':break
        iid+=1
    path=profile/f'instance-settings-{iid}.xml'
    values={'kodi_addon_instance_name':'Nuvio IPTV','kodi_addon_instance_enabled':'true',
            'm3uPathType':'1','m3uUrl':m3u,'m3uCache':'true','epgPathType':'1','epgUrl':epg,
            'epgCache':'true','m3uRefreshMode':'2','m3uRefreshHour':'4','numberByOrder':'false'}
    root=ET.Element('settings',version='2')
    for key,value in values.items():ET.SubElement(root,'setting',id=key).text=value
    temp=path.with_suffix('.tmp');ET.ElementTree(root).write(temp,encoding='utf-8',xml_declaration=True)
    if path.exists():
        backup=profile/'nuvio-backups';backup.mkdir(exist_ok=True)
        (backup/(str(time.time_ns())+'.xml')).write_bytes(path.read_bytes())
    os.replace(temp,path)
    try:os.chmod(path,0o600)
    except OSError:pass
    return iid
