"""REST API for calculating rigor."""
import string
import os
import subprocess
import urllib
import shutil
import random
from queue import SimpleQueue
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename
import werkzeug.exceptions
from google.cloud import vision
import PyPDF2

if not os.path.isdir('./submissions'):
    os.mkdir('./submissions')

app = Flask(__name__) # pylint: disable=invalid-name
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.config['GHOSTSCRIPT_PATH'] = os.environ['GHOSTSCRIPT_PATH']

@app.after_request
def apply_headers(response):
    """Add headers to every response."""
    response.headers['Access-Control-Allow-Origin'] = 'https://keanemind.github.io'
    response.headers['Access-Control-Allow-Methods'] = 'POST, GET, OPTIONS, PUT'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, X-Requested-With'
    response.headers['Vary'] = 'Origin'
    return response

@app.errorhandler(werkzeug.exceptions.RequestEntityTooLarge)
def handle_too_large(error):
    """Handle error when request is too large."""
    response = jsonify({'error': 'Upload too large.'})
    response.status_code = error.status_code
    return response

@app.route('/text', methods=('POST',))
def text_rigor():
    """Return the rigor of text."""
    return jsonify({'result': str_rigor(request.json['text'])})

@app.route('/pdf', methods=('POST',))
def pdf_rigor():
    """Return the rigor of a PDF."""
    file = request.files.get('file')
    if not file or not file.filename or not file.filename.endswith('.pdf'):
        return jsonify({'error': 'Invalid file.'})

    filename = secure_filename(file.filename)
    filepath = os.path.join('./submissions', filename)
    file.save(filepath)
    return pdf_response(filepath)


@app.route('/image', methods=('POST',))
def image_rigor():
    """Return the rigor of an image."""
    file = request.files.get('file')
    if not file or not file.filename or not file.filename.endswith(
            ('.jpeg', '.jpg', '.png', '.gif', '.bmp', '.tiff')
    ):
        return jsonify({'error': 'Not an accepted file format.'})

    filename = secure_filename(file.filename)
    filepath = os.path.join('./submissions', filename)
    file.save(filepath)

    text = img_to_text(filepath)
    os.remove(filepath)
    return jsonify({'result': str_rigor(text)})

@app.route('/url', methods=('POST',))
def url_rigor():
    """Return the rigor of a PDF or image URL."""
    url = request.json['url']

    # Check that URL is pdf or image
    if not url.endswith(
            ('.jpeg', '.jpg', '.png', '.gif', '.bmp', '.tiff', '.pdf')
    ):
        return jsonify({'error': 'Not an accepted file format.'})

    try:
        resp = urllib.request.urlopen(url)
    except urllib.error.URLError:
        return jsonify({'error': 'Invalid URL.'})

    # Download file
    parsed_url = urllib.parse.urlparse(url)
    filename = os.path.basename(parsed_url.path)
    filepath = os.path.join('./submissions', filename)
    with open(filepath, 'wb') as out_file:
        shutil.copyfileobj(resp, out_file) # TODO: limit file size

    if filename.endswith('.pdf'):
        return pdf_response(filepath)

    text = img_to_text(filepath)
    os.remove(filepath)
    return jsonify({'result': str_rigor(text)})

def generate_search_graph(patterns: list):
    """Generate an Aho-Corasick graph from a list of patterns."""
    # Adjacency list
    graph = [
        {
            'value': '',
            'parent': None,
            'children': {},
            'suffix': None,
            'dict_suffix': None,
            'is_pattern': False,
        },
    ]

    # Create trie
    for pattern in patterns:
        # Insert pattern into graph
        cur_node = graph[0]
        cur_node_idx = 0
        prefix = ''
        for idx, char in enumerate(pattern):
            prefix += char

            # Search for next node, add it if not found
            child_idx = cur_node['children'].get(char)
            if child_idx:
                child = graph[child_idx]
            else:
                child = {
                    'value': prefix,
                    'parent': cur_node_idx,
                    'children': {},
                    'suffix': None,
                    'dict_suffix': None,
                    'is_pattern': False,
                }
                child_idx = len(graph)
                graph.append(child)
                cur_node['children'][char] = child_idx

            if idx == len(pattern) - 1:
                child['is_pattern'] = True

            cur_node = child
            cur_node_idx = child_idx

    # Add suffix links
    queue = SimpleQueue()
    queue.put(0)
    while not queue.empty():
        cur_node_idx = queue.get(block=False)
        cur_node = graph[cur_node_idx]

        if cur_node['parent'] == 0:
            cur_node['suffix'] = 0
        elif cur_node_idx != 0:
            cur_node_char = cur_node['value'][-1]

            # Start from parent
            parent_node = graph[cur_node['parent']]
            while not cur_node['suffix']:
                # If we got to the root node, set the empty
                # string as the longest strict suffix.
                if parent_node is graph[0]:
                    cur_node['suffix'] = 0
                    break

                # Traverse suffix link
                parent_node = graph[parent_node['suffix']]
                child_idx = parent_node['children'].get(cur_node_char)
                if child_idx:
                    cur_node['suffix'] = child_idx

        for child_idx in cur_node['children'].values():
            queue.put(child_idx)

    # Add dict_suffix links
    # TODO: memoize
    queue = SimpleQueue()
    queue.put(0)
    while not queue.empty():
        cur_node_idx = queue.get(block=False)
        cur_node = graph[cur_node_idx]

        travel_node_idx = cur_node_idx
        travel_node = cur_node
        while travel_node is not graph[0]:
            # Traverse suffix link
            travel_node_idx = travel_node['suffix']
            travel_node = graph[travel_node_idx]

            if travel_node['is_pattern']:
                cur_node['dict_suffix'] = travel_node_idx
                break

        for child_idx in cur_node['children'].values():
            queue.put(child_idx)

    return graph

def execute_search_graph(graph, text: str):
    """Execute an Aho-Corasick search. Yields matches."""
    cur_node = graph[0]
    for char in text:
        # Move to the next node
        next_node_idx = cur_node['children'].get(char)
        while not next_node_idx and cur_node is not graph[0]:
            cur_node = graph[cur_node['suffix']] # pylint: disable=invalid-sequence-index
            next_node_idx = cur_node['children'].get(char)
        if not next_node_idx:
            next_node_idx = 0
        cur_node = graph[next_node_idx]

        # Output matches
        out_node = cur_node
        while out_node['dict_suffix']:
            out_node = graph[out_node['dict_suffix']]
            yield out_node['value']
        if cur_node['is_pattern']:
            yield cur_node['value']

def calculate_rigor(text: str):
    """Calculate the rigor of text."""
    score = 99
    matches = execute_search_graph(GRAPH, text)
    for match in matches:
        score = RULES[match](score)

    return score

def str_rigor(text: str):
    """Normalize the input text and then calculate its rigor."""
    normalized = ' '.join(text.translate(
        str.maketrans(string.punctuation, len(string.punctuation) * ' ')
    ).split()).lower()
    return calculate_rigor(normalized)

def img_to_text(path: str):
    """Convert an image to text."""
    client = vision.ImageAnnotatorClient()
    filename = os.path.abspath(path)

    with open(filename, 'rb') as image_file:
        content = image_file.read()

    image = vision.types.Image(content=content) # pylint: disable=no-member
    response = client.document_text_detection(image) # pylint: disable=no-member

    return response.full_text_annotation.text

    # for page in response.full_text_annotation.pages:
    #     for block in page.blocks:
    #         print('\nBlock confidence: {}\n'.format(block.confidence))

    #         for paragraph in block.paragraphs:
    #             print('Paragraph confidence: {}'.format(
    #                 paragraph.confidence))

    #             for word in paragraph.words:
    #                 word_text = ''.join([
    #                     symbol.text for symbol in word.symbols
    #                 ])
    #                 print('Word text: {} (confidence: {})'.format(
    #                     word_text, word.confidence))

    #                 for symbol in word.symbols:
    #                     print('\tSymbol: {} (confidence: {})'.format(
    #                         symbol.text, symbol.confidence))

def pdf_response(filepath):
    """Generate a response from a PDF."""
    # Determine if PDF is text or image
    rnd_str = ''.join(random.choice(string.ascii_uppercase + string.digits) for _ in range(10))
    txt_filename = 'output{}.txt'.format(rnd_str)
    subprocess.call([app.config['GHOSTSCRIPT_PATH'], '-sDEVICE=txtwrite', '-dFILTERIMAGE', '-o', txt_filename, filepath]) # pylint: disable=line-too-long

    pdf = PyPDF2.PdfFileReader(filepath)
    num_pages = pdf.getNumPages()

    with open(txt_filename, 'r') as text_file:
        text = text_file.read()
        is_probably_scanned = len(text.split()) / num_pages < 20

    os.remove(filepath)
    os.remove('./' + txt_filename)

    if not is_probably_scanned:
        return jsonify({'result': str_rigor(text)})

    return jsonify(
        {'error': 'This looks like a scanned PDF. Please submit a text PDF.'}
    )

RULES = {
    'assume': lambda cur: cur + 0.3,
    'suppose': lambda cur: cur + 0.3,
    'hence': lambda cur: cur + 1,
    'since': lambda cur: cur + 1,
    'then': lambda cur: cur + 1,
    'therefore': lambda cur: cur + 1,
    'thus': lambda cur: cur + 1,
    'it follows': lambda cur: cur + 1,
    'without loss of generality': lambda cur: (cur**1.05).real,
    'wlog': lambda cur: (cur**1.05).real,
    'by definition': lambda cur: cur + 2,
    'by hypothesis': lambda cur: cur + 3,
    'by the inductive hypothesis': lambda cur: cur * 1.5,
    'by the induction hypothesis': lambda cur: cur * 1.5,
    'by inductive hypothesis': lambda cur: cur * 1.5,
    'by induction': lambda cur: cur * 1.5,
    'by symmetry': lambda cur: cur + 30,
    'case': lambda cur: cur + 1,
    'claim': lambda cur: cur + 5,
    'lemma': lambda cur: cur + 10,
    'clearly': lambda cur: cur - 11,
    'obviously': lambda cur: cur - 22,
    'trivial': lambda cur: cur - 33,
    'of course': lambda cur: cur - 33,
    'in particular': lambda cur: cur * 1.1,
    'qed': lambda cur: cur + 50,
    'where': lambda cur: cur - 0.5,
}

GRAPH = generate_search_graph(RULES.keys())
