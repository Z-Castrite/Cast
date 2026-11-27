package com.castrite.twobody;

/** 一个智能体。名字只是显示用的，它的性格在 persona.txt 里。 */
public class Agent {

    public final long id;
    public final String name;

    public Agent(long id, String name) {
        this.id = id;
        this.name = name;
    }
}
