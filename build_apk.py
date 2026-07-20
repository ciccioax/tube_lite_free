#!/usr/bin/env python3
"""
Build TubeLite APK using real Android tools (javac, d8, aapt2).
JDK and Android build-tools are downloaded to /tmp/.
"""
import os, subprocess, shutil, zipfile, struct, hashlib, zlib

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
URL = "https://menfis2028.pythonanywhere.com"
PACKAGE = "com.tubelite.app"
APP_LABEL = "TubeLite"

JAVA_HOME = '/tmp/jdk-17.0.13+11'
BUILD_TOOLS = '/tmp/android-sdk/android-14'
JAVAC = os.path.join(JAVA_HOME, 'bin', 'javac')
KEYTOOL = os.path.join(JAVA_HOME, 'bin', 'keytool')
JARSIGNER = os.path.join(JAVA_HOME, 'bin', 'jarsigner')
D8 = os.path.join(BUILD_TOOLS, 'd8')
AAPT2 = os.path.join(BUILD_TOOLS, 'aapt2')
ANDROID_JAR = '/tmp/android-sdk/platform/android-34/android.jar'

WORK_DIR = os.path.join(BASE_DIR, '_build_tmp')

JAVA_SRC = f"""\
package {PACKAGE};

import android.app.Activity;
import android.os.Bundle;
import android.webkit.WebView;
import android.webkit.WebSettings;
import android.webkit.WebViewClient;

public class MainActivity extends Activity {{
    @Override
    protected void onCreate(Bundle savedInstanceState) {{
        super.onCreate(savedInstanceState);
        WebView wv = new WebView(this);
        WebSettings s = wv.getSettings();
        s.setJavaScriptEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setDomStorageEnabled(true);
        wv.setWebViewClient(new WebViewClient());
        wv.loadUrl("{URL}");
        setContentView(wv);
    }}
}}
"""

MANIFEST_XML = f"""\
<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android"
    package="{PACKAGE}"
    android:versionCode="1"
    android:versionName="1.0">

    <uses-sdk android:minSdkVersion="21" android:targetSdkVersion="34" />
    <uses-permission android:name="android.permission.INTERNET" />

    <application
        android:label="{APP_LABEL}"
        android:usesCleartextTraffic="true"
        android:hasCode="true">

        <activity
            android:name=".MainActivity"
            android:exported="true">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>
    </application>
</manifest>
"""


def run(cmd, **kw):
    print(f"  $ {' '.join(cmd)}")
    env = os.environ.copy()
    env['JAVA_HOME'] = JAVA_HOME
    env['PATH'] = os.path.join(JAVA_HOME, 'bin') + ':' + env.get('PATH', '')
    r = subprocess.run(cmd, capture_output=True, text=True, env=env, **kw)
    if r.returncode != 0:
        print(f"  STDERR: {r.stderr[:500]}")
        raise RuntimeError(f"Command failed: {' '.join(cmd[:3])}")
    return r


def build():
    # Clean
    if os.path.exists(WORK_DIR):
        shutil.rmtree(WORK_DIR)
    os.makedirs(WORK_DIR)
    os.makedirs(os.path.join(WORK_DIR, 'src', PACKAGE.replace('.', '/')))

    # 1. Write Java source
    src_file = os.path.join(WORK_DIR, 'src', PACKAGE.replace('.', '/'), 'MainActivity.java')
    with open(src_file, 'w') as f:
        f.write(JAVA_SRC)

    # 2. Write manifest
    manifest_file = os.path.join(WORK_DIR, 'AndroidManifest.xml')
    with open(manifest_file, 'w') as f:
        f.write(MANIFEST_XML)

    # 3. Compile with javac
    print("Compiling Java...")
    run([JAVAC, '-source', '1.7', '-target', '1.7',
         '-classpath', ANDROID_JAR,
         '-d', os.path.join(WORK_DIR, 'classes'),
         src_file])

    # 4. Convert to DEX with d8
    print("Converting to DEX...")
    class_files = []
    for root, dirs, files in os.walk(os.path.join(WORK_DIR, 'classes')):
        for f in files:
            if f.endswith('.class'):
                class_files.append(os.path.join(root, f))

    run([D8, '--output', os.path.join(WORK_DIR),
         '--min-api', '21',
         '--lib', ANDROID_JAR] + class_files)

    dex_path = os.path.join(WORK_DIR, 'classes.dex')
    if not os.path.exists(dex_path):
        # d8 might put it in a subdirectory
        for root, dirs, files in os.walk(WORK_DIR):
            for f in files:
                if f == 'classes.dex':
                    dex_path = os.path.join(root, f)

    print(f"  DEX: {os.path.getsize(dex_path)} bytes")

    # 5. Package with aapt2
    print("Packaging APK...")
    compiled_res = os.path.join(WORK_DIR, 'compiled_res')
    os.makedirs(compiled_res)

    # aapt2 compile (no resources to compile, but we need the link step)
    unsigned_apk = os.path.join(WORK_DIR, 'unsigned.apk')

    run([AAPT2, 'link',
         '--manifest', manifest_file,
         '--min-sdk-version', '21',
         '--target-sdk-version', '34',
         '-I', ANDROID_JAR,
         '-o', unsigned_apk,
         '--auto-add-overlay'])

    # 6. Add classes.dex to the APK
    with zipfile.ZipFile(unsigned_apk, 'a') as zf:
        zf.write(dex_path, 'classes.dex')

    print(f"  Unsigned APK: {os.path.getsize(unsigned_apk)} bytes")

    # 7. Sign with apksigner (v2/v3 signature)
    print("Signing APK (v1+v2+v3)...")
    keystore = os.path.join(BASE_DIR, 'debug.keystore')
    if not os.path.exists(keystore):
        run([KEYTOOL, '-genkeypair', '-v',
             '-keystore', keystore,
             '-storepass', 'android',
             '-alias', 'androiddebugkey',
             '-keypass', 'android',
             '-keyalg', 'RSA',
             '-keysize', '2048',
             '-validity', '10000',
             '-dname', 'CN=Debug,OU=Debug,O=Debug,L=Debug,ST=Debug,C=US'])

    signed_apk = os.path.join(BASE_DIR, 'TubeLite.apk')
    # Copy unsigned to final location, then sign in-place
    shutil.copy2(unsigned_apk, signed_apk)
    apksigner_jar = os.path.join(BUILD_TOOLS, 'lib', 'apksigner.jar')
    run(['java', '-jar', apksigner_jar, 'sign',
         '--ks', keystore,
         '--ks-pass', 'pass:android',
         '--key-pass', 'pass:android',
         signed_apk])

    print(f"\nDone! APK: {signed_apk}")
    print(f"Size: {os.path.getsize(signed_apk)} bytes")

    # Copy to deploy for download
    deploy_apk = os.path.join(BASE_DIR, 'deploy', 'tubelite.apk')
    shutil.copy2(signed_apk, deploy_apk)
    print(f"Copied to: {deploy_apk}")

    # Clean up
    shutil.rmtree(WORK_DIR)
    return signed_apk


if __name__ == '__main__':
    build()
