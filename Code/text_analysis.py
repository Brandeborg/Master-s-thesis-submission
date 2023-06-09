from data_preparation import load_json, save_json
from nltk.stem.porter import PorterStemmer
from nltk import word_tokenize, sent_tokenize
from nltk.util import ngrams
from nltk.corpus import stopwords
import string

from transformers import pipeline
from sklearn.feature_extraction.text import TfidfVectorizer

# --- This file contains functions in charge of performing text analysis on text generated by the generative models --- #

### KEYWORD COUNT ###
def get_normalized_ngrams(seq: str):
    """Given a sequence of sentences, returns a tuple with a list of stemmed unigrams, bigrams and trigrams

    Args:
        seq (str): A raw seqeunce of sentences

    Returns:
        tuple: Three lists. Each list contains token ngrams. One where tokens are unigrams, bigrams and trigrams. Tokens are stemmed, lowered, without stopwords and punctuation.
    """
    # split sequence up into sentences
    sentences = sent_tokenize(seq.lower(), language="english")

    stemmer = PorterStemmer()
    stops = set(stopwords.words("english") + list(string.punctuation) + ["'s", "``", "’", "''", "--", "—", "–", "“", "”"]) 

    # tokenize sententces and stem each word
    stemmed_sentences = []
    for sentence in sentences:
        tokens = word_tokenize(sentence)
        stemmed_tokens = [stemmer.stem((token)) for token in tokens if token not in stops]
        stemmed_sentences.append(stemmed_tokens)
    
    # extract uni-, bi, and trigrams from the sentences
    stemmed_unigrams = [unigram for sent in stemmed_sentences for unigram in sent]
    stemmed_bigrams = [" ".join(bigram) for sent in stemmed_sentences for bigram in list(ngrams(sent, 2))]
    stemmed_trigrams = [" ".join(trigram) for sent in stemmed_sentences for trigram in list(ngrams(sent, 3))]

    return stemmed_unigrams, stemmed_bigrams, stemmed_trigrams

### TF ###
def count_ngrams(seqs: list, top_n=20, min_freq=2, topic_keywords=[]):
    """Given a list of text sequences, counts the uni-, bi- and trigrams after normalizing the text. 

    Args:
        seqs (list): Raw text sequences
        top_n (int, optional): How many of the top ngrams to include in each category(uni, bi, tri). Defaults to 20.
        min_freq (int, optional): Minimum frequency of an ngram to be included in the top list. Defaults to 2.
        topic_keywords (list, optional): A list of normalized keywords that should ne excluded from the count. If "seqs" has a specific topic (e.g. Donald Trump),
        it is probably a given, that those words appears in top 2, so here is the option to exclude them. Defaults to [].

    Returns:
        dict: {1: {"term": 2, ...}, 2: {}, 3: {}}
    """
    # fill up dict with lists of all n-grams
    all_ngrams = {1: [], 2:[], 3:[]}
    for seq in seqs:
        uni, bi, tri = get_normalized_ngrams(seq)
        all_ngrams[1].extend(uni)
        all_ngrams[2].extend(bi)
        all_ngrams[3].extend(tri)

    # count the freuqnecy of each term
    counts = {1:{}, 2:{}, 3:{}}
    for key in all_ngrams:
        for ngram in all_ngrams[key]:
            # if the ngram shares keywords with the initial prompt topic, don't include it in the counts
            skip_ngram = False
            for keyword in topic_keywords:
                if keyword in ngram:
                    skip_ngram = True
                    break
            if skip_ngram:
                continue

            # count ngrams
            if ngram not in counts[key]:
                counts[key][ngram] = 1
            else:
                counts[key][ngram] += 1

        # sort counts by value
        counts[key] = dict(sorted(counts[key].items(), key=lambda item: item[1], reverse=True))
        counts[key] = {k: v for k, v in list(counts[key].items())[:top_n] if v >= min_freq}

    return counts

def count_ngrams_in_generated_text(filepath, save_name):
    """Load the json from file path, and count the ngrams in each topic and the total. 

    Args:
        filepath (str): Path to json file. Expected format: {-TOPIC-: {"greedy": ["Some generated text", ...], "sampling": ["Some generated text", ...]}, ...}
        save_name (str): path and name of the json file where the result is saved.
    """
    gen_text = load_json(file_path=filepath)

    counts = {}
    all_text_sampling = []
    all_topic_keywords = []
    for topic in gen_text:
        # normaize keywords from the prompt topic
        topic_keywords, _, _ = get_normalized_ngrams(topic)
        all_topic_keywords.extend(topic_keywords)

        # add the text strings to the list of all text strings
        all_text_sampling.extend(gen_text[topic]["sampling"])

        # count ngrams for the current topic
        counts[topic] = count_ngrams(gen_text[topic]["sampling"], 20, 2, topic_keywords=topic_keywords)
    
    # count ngrams for the all topics
    counts["All"] = count_ngrams(all_text_sampling, 20, 2, topic_keywords=all_topic_keywords)

    save_json(counts, save_name)

### TFIDF ###
def count_ngrams_tfidf(all_seqs: list, topic_seqs: list, top_n=20, topic_keywords=[]):
    """Given a list of topic documents, calculate tfidf scores for each feature compared to entire corpus of documents. The tfidf scores are calculated for
    each document in the topic, and the scores for each feature is summed. The top_n words in each ngram-category is found and returned.

    Args:
        all_seqs (list): List of all documents, including topic_seqs
        topic_seqs (list): List of documents generated from a specific topic
        top_n (int, optional): How many of the top ngrams to include in each category(uni, bi, tri). Defaults to 20.
        topic_keywords (list, optional): A list of normalized keywords that should be excluded from the count. If "seqs" has a specific topic (e.g. Donald Trump),
        it is probably a given, that those words appear in top 2, so here is the option to exclude them. Defaults to [].

    Returns:
        dict: {1: {"term": 2, ...}, 2: {}, 3: {}}
    """
    # added "-" to the token pattern because the original was inconsistent with the word_tokenize() step in get_normalized_ngrams().
    # the original split up "covid-19" or "jong-un" which it should not
    vectorizer = TfidfVectorizer(stop_words=topic_keywords, ngram_range=(1,3), max_features=5000, token_pattern=r'(?u)\b[\w\-]+\b')

    # learn vocab and idf of all sequences
    X = vectorizer.fit(all_seqs)

    # get tfidf scores for topic sequences
    tfidf_matrix = vectorizer.transform(topic_seqs).toarray()

    # extract feature names
    features = vectorizer.get_feature_names_out()

    scores = {1:{}, 2:{}, 3:{}}
    # iterate over terms
    for i, feature in enumerate(features):
        # iterate over documents
        for row in tfidf_matrix:
            # get the score of the term in a specific document
            score = row[i]
            # if the score is more than 0, meaning the term exists in the document, add it to the sum of the scores of the term
            if score > 0:
                # get the ngram type (uni, bi, tri / 1,2,3)
                feature_word_count = len(feature.split(" "))
                # add the term score to the term score sum at the appropriate ngram group
                if feature in scores[feature_word_count]:
                    scores[feature_word_count][feature] += score
                else:
                    scores[feature_word_count][feature] = score

    # sort the score sums for in a descending order for each ngram group
    scores = {ngram_count: dict(sorted(scores[ngram_count].items(), key=lambda item: item[1], reverse=True)[:top_n]) for ngram_count in scores}

    return scores

def count_ngrams_tfidf_in_generated_text(filepath, save_name):
    """Load the json from file path, and calculate tfidf score for the ngrams in each topic and the total. 

    Args:
        filepath (str): Path to json file. Expected format: {-TOPIC-: {"greedy": ["Some generated text", ...], "sampling": ["Some generated text", ...]}, ...}
        save_name (str): path and name of the json file where the result is saved.
    """
    gen_text = load_json(file_path=filepath)

    scores = {}
    # normalize all sequences from each topic and add them a list per topic
    all_text_sampling_per_topic = {topic: [" ".join(get_normalized_ngrams(text)[0]) for text in gen_text[topic]["sampling"]] for topic in gen_text}

    # add all normalized sequences to single list
    all_text_sampling = [text for topic in all_text_sampling_per_topic for text in all_text_sampling_per_topic[topic]]

    all_topic_keywords = []
    for topic in all_text_sampling_per_topic:
        # normaize keywords from the propmt topic
        topic_keywords, _, _ = get_normalized_ngrams(topic)
        all_topic_keywords.extend(topic_keywords)

        # count ngrams for the current topic
        scores[topic] = count_ngrams_tfidf(all_text_sampling, all_text_sampling_per_topic[topic], 20, topic_keywords=topic_keywords)
    
    # count ngrams for the all topics
    scores["All"] = count_ngrams_tfidf(all_text_sampling, all_text_sampling, 20, topic_keywords=all_topic_keywords)

    save_json(scores, save_name)

### SENTIMENT ###
def get_sentiments(seqs):
    """Given a sequence, use a model to predicts its sentiment (NEG or POS)

    Args:
        seqs (str): Some text sequence

    Returns:
        dict: dict with label (pos or neg) and a score
    """
    # Models:
    # distilbert-base-uncased-finetuned-sst-2-english (default)
    # siebert/sentiment-roberta-large-english
    classifier = pipeline("sentiment-analysis", model="siebert/sentiment-roberta-large-english")
    return classifier(seqs)

def get_average_semtiment(sentiments):
    """Given a list of sentiments, calculates and returns the average among the negative labels, positive labels and overall.

    Args:
        sentiments (list): List of dicts of sentiments scores

    Returns:
        dict: dict of averages
    """
    pos = []
    neg = []
    all = []
    for sentiment in sentiments:
        if sentiment["label"] == "POSITIVE":
            pos.append(sentiment["score"])
            all.append(sentiment["score"])
        else:
            neg.append(sentiment["score"])
            all.append(sentiment["score"] * -1)
    
    avgs = {}
    avgs["avg_pos"] = sum(pos) / len(pos)
    avgs["avg_all"] = sum(all) / len(all)
    avgs["avg_neg"] = sum(neg) / len(neg)

    return avgs

def get_average_sentiment_in_generated_text(filepath, save_name):
    """Loads the generated text from filepath, calculates the average sentiments and saves them.

    Args:
        filepath (str): Path to generated text
        save_name (str): Name of file where results are saved.
    """
    gen_text = load_json(file_path=filepath)

    avgs = {}
    all_sentiments = []
    for topic in gen_text:
        sentiments = get_sentiments(gen_text[topic]["sampling"])
        all_sentiments.extend(sentiments)
        avgs[topic] = get_average_semtiment(sentiments)

    avgs["All"] = get_average_semtiment(all_sentiments)

    save_json(avgs, save_name)

def main():
    """Run all the text analysis steps on the generated text.
    """
    get_average_sentiment_in_generated_text("results/generated_text_GenGPT.json","results/generated_text_GenGPT_sentiment.json")
    get_average_sentiment_in_generated_text("results/generated_text_NewsGPT.json","results/generated_text_NewsGPT_sentiment.json")
    get_average_sentiment_in_generated_text("results/generated_text_GenNewsGPT.json","results/generated_text_GenNewsGPT_sentiment.json")

    count_ngrams_in_generated_text("results/generated_text_GenGPT.json","results/generated_text_GenGPT_term_freq.json")
    count_ngrams_in_generated_text("results/generated_text_NewsGPT.json","results/generated_text_NewsGPT_term_freq.json")
    count_ngrams_in_generated_text("results/generated_text_GenNewsGPT.json","results/generated_text_GenNewsGPT_term_freq.json")

    count_ngrams_tfidf_in_generated_text("results/generated_text_GenGPT.json","results/generated_text_GenGPT_tfidf.json")
    count_ngrams_tfidf_in_generated_text("results/generated_text_NewsGPT.json","results/generated_text_NewsGPT_tfidf.json")
    count_ngrams_tfidf_in_generated_text("results/generated_text_GenNewsGPT.json","results/generated_text_GenNewsGPT_tfidf.json")

if __name__ == "__main__":
    main()